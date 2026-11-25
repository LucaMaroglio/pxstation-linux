"""Sessions shown by remote-viewer, with automatic reconnection through the Proxmox API.

remote-viewer runs as a child process with ``G_MESSAGES_DEBUG=virt-viewer``; its debug
lines tell how a session ended (verified with remote-viewer 11):

* ``main channel: opened``                       → connected
* ``main channel: closed`` *before* ``zap main channel``
  (or ``… display has disconnected, shutting down``) → the server side went away
* ``zap main channel`` *before* ``main channel: closed`` → the user closed the window
  (remote-viewer tears its channels down first)
* ``main channel: failed to connect …``          → could not connect (before ``opened``)
  or an I/O error on an open connection (after it)
* ``main channel: auth failure …``               → ticket rejected

Reconnection follows the macOS client's ``ReconnectPolicy``: only a dropped connection
starts it, every attempt fetches a fresh one-time ticket, attempts back off and stop after
eight tries, and a session that stayed up for a minute starts over at attempt 1.
"""

from __future__ import annotations

import enum
import itertools
import logging
import os
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass

from gi.repository import Gio, GLib

from .. import APP_SLUG
from . import vvfile
from .proxmox import Forbidden, PowerAction, ProxmoxError, ProxmoxServer, Unauthorized
from .util import error_text, run_in_thread
from .vvfile import VMRef
from .i18n import _

log = logging.getLogger(__name__)

REMOTE_VIEWER = "remote-viewer"


# MARK: Policy


@dataclass(frozen=True)
class ReconnectPolicy:
    delays: tuple[float, ...] = (1, 2, 4, 8, 15, 30, 30, 30)
    stable_after: float = 60

    @property
    def max_attempts(self) -> int:
        return len(self.delays)

    def delay(self, attempt: int) -> float | None:
        """Wait before the 1-based ``attempt``, or ``None`` to give up."""
        if 1 <= attempt <= len(self.delays):
            return self.delays[attempt - 1]
        return None


class Outcome(enum.Enum):
    USER_CLOSED = "user"
    DROPPED = "dropped"
    CONNECT_FAILED = "connect-failed"
    AUTH_FAILED = "auth-failed"
    CRASHED = "crashed"


class ViewerLog:
    """Tracks one remote-viewer run from its debug output."""

    def __init__(self):
        self.opened = False
        self.closed_by_server = False
        self.zapped = False
        self.disconnected = False
        self.connect_failed: str | None = None
        self.io_error = False
        self.auth_failed = False
        self.window_closed = False

    def feed(self, line: str) -> str | None:
        """Returns the event the line represents, if any."""
        if "main channel: opened" in line:
            self.opened = True
            return "opened"
        if "main channel: closed" in line:
            if not self.zapped:
                self.closed_by_server = True
            return "closed"
        if "zap main channel" in line:
            self.zapped = True
            return None
        if "display has disconnected" in line:
            self.disconnected = True
            return "disconnected"
        if "main channel: failed to connect" in line:
            if self.opened:
                self.io_error = True
                return "io-error"
            self.connect_failed = line.split("main channel: failed to connect", 1)[1].strip()
            return "connect-failed"
        if "main channel: auth failure" in line:
            self.auth_failed = True
            return "auth-failed"
        if line.rstrip().endswith("Window closed"):
            self.window_closed = True
            return "window-closed"
        return None

    def outcome(self, exit_ok: bool) -> Outcome:
        if self.auth_failed and not self.opened:
            return Outcome.AUTH_FAILED
        if self.connect_failed is not None and not self.opened:
            return Outcome.CONNECT_FAILED
        if self.opened and (self.closed_by_server or self.disconnected or self.io_error):
            return Outcome.DROPPED
        if not exit_ok:
            return Outcome.DROPPED if self.opened else Outcome.CRASHED
        return Outcome.USER_CLOSED


# MARK: Session


class State(enum.Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ENDED = "ended"


class EndKind(enum.Enum):
    DROPPED = "dropped"              # could reconnect manually
    VM_NOT_RUNNING = "vm-off"        # offer Start & Reconnect
    NO_API = "no-api"                # Proxmox VM but no server configured
    ONE_TIME_TICKET = "one-time"     # downloaded file, not Proxmox
    GAVE_UP = "gave-up"
    CANCELLED = "cancelled"
    ERROR = "error"


_ids = itertools.count(1)


class Session:
    def __init__(self, manager: "SessionManager", title: str, ref: VMRef | None, vm_name: str | None = None):
        self.manager = manager
        self.id = next(_ids)
        self.title = title
        self.vm_name = vm_name or title
        self.ref = ref
        self.state = State.CONNECTING
        self.attempt = 0
        self.retry_at: float | None = None
        self.waiting_for_network = False
        self.end_kind: EndKind | None = None
        self.end_message: str | None = None
        self.busy = False  # power action / start in progress

        self._process: Gio.Subprocess | None = None
        self._log: ViewerLog | None = None
        self._temp_path: str | None = None
        self._opened_at: float | None = None
        self._user_ending = False
        self._expect_end_until = 0.0
        self._log_file = None
        self._log_path: str | None = None
        self._partial = ""
        self._poll: int | None = None
        self._exit_ok = True
        self._timer: int | None = None
        self._network_handler: int | None = None
        self._initial = True

    # Info

    @property
    def server(self) -> ProxmoxServer | None:
        return self.manager.store.server_for_host(self.ref.api_host) if self.ref else None

    @property
    def can_control_power(self) -> bool:
        return self.server is not None

    @property
    def is_active(self) -> bool:
        return self.state in (State.CONNECTING, State.CONNECTED, State.RECONNECTING)

    @property
    def max_attempts(self) -> int:
        return self.manager.policy.max_attempts

    def status_text(self) -> str:
        if self.state == State.CONNECTING:
            return _("Connecting…")
        if self.state == State.CONNECTED:
            return _("Connected")
        if self.state == State.RECONNECTING:
            if self.waiting_for_network:
                return _("Waiting for the network…")
            if self.retry_at:
                seconds = max(0, round(self.retry_at - time.monotonic()))
                return _("Reconnecting in {seconds} s (attempt {attempt}/{total})").format(seconds=seconds, attempt=self.attempt, total=self.max_attempts)
            return _("Reconnecting… (attempt {attempt}/{total})").format(attempt=self.attempt, total=self.max_attempts)
        return self.end_message or _("Ended")

    def expect_end(self) -> None:
        """A shutdown/stop was requested: the next drop is expected, don't reconnect."""
        self._expect_end_until = time.monotonic() + 300

    # Launching remote-viewer

    def launch(self, values: dict[str, str], path: str | None = None) -> None:
        """Starts remote-viewer for ``values`` (written to a private temp file) or for the
        user's own file at ``path``."""
        self._cancel_timer()
        if path is None:
            path = self._write_temp(values)
        args = [REMOTE_VIEWER]
        if self.manager.settings.open_full_screen:
            args.append("--full-screen")
        args.append(path)

        # remote-viewer's messages go to a private file, not a pipe: if this program quits
        # or crashes, the viewer must not die of SIGPIPE on its next log line.
        log_fd, log_path = tempfile.mkstemp(dir=_runtime_dir(), prefix="viewer-", suffix=".log")
        # GLib's default handler prints debug messages on stdout and warnings on stderr.
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDERR_MERGE)
        launcher.setenv("G_MESSAGES_DEBUG", "virt-viewer", True)
        launcher.set_stdout_file_path(log_path)
        try:
            process = launcher.spawnv(args)
        except GLib.Error as error:
            os.close(log_fd)
            _unlink(log_path)
            self._remove_temp()
            self._end(EndKind.ERROR, _("Can’t start remote-viewer: {error}").format(error=error.message))
            return

        # An activation token that came with the request (a .vv opened from Dolphin or the
        # browser) was inherited by remote-viewer, whose window is the one to bring to the
        # front. Tokens are single-use: drop it so no later launch reuses it.
        os.environ.pop("XDG_ACTIVATION_TOKEN", None)
        os.environ.pop("DESKTOP_STARTUP_ID", None)

        self._process = process
        self._log = ViewerLog()
        self._log_file = os.fdopen(log_fd, "r", encoding="utf-8", errors="replace")
        self._log_path = log_path
        self._partial = ""
        self._user_ending = False
        self._opened_at = None
        self._exit_ok = True
        self.retry_at = None
        self.waiting_for_network = False
        self._set_state(State.CONNECTING if self.attempt == 0 else State.RECONNECTING)

        self._poll = GLib.timeout_add(200, self._read_log, process)
        process.wait_async(None, self._on_exit, process)

    def _write_temp(self, values: dict[str, str]) -> str:
        fd, path = tempfile.mkstemp(dir=_runtime_dir(), prefix="session-", suffix=".vv")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(vvfile.serialize(values))
        self._temp_path = path
        return path

    def _remove_temp(self) -> None:
        if self._temp_path:
            _unlink(self._temp_path)
            self._temp_path = None

    def _read_log(self, process) -> bool:
        if process is not self._process or self._log_file is None:
            return False
        chunk = self._log_file.read()
        if chunk:
            lines = (self._partial + chunk).split("\n")
            self._partial = lines.pop()
            for line in lines:
                self._on_line(process, line)
                if process is not self._process:
                    return False
        return True

    def _close_log(self) -> None:
        if self._poll is not None:
            GLib.source_remove(self._poll)
            self._poll = None
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if self._log_path:
            _unlink(self._log_path)
            self._log_path = None

    def _on_line(self, process, line: str):
        event = self._log.feed(line)
        if event == "opened":
            self._remove_temp()  # remote-viewer has read it; the ticket is spent anyway
            self._opened_at = time.monotonic()
            was_reconnect = self.attempt > 0
            self._initial = False
            self._set_state(State.CONNECTED)
            if was_reconnect:
                self.manager.notify(self, _("Reconnected"), _("The session with {title} is active again.").format(title=self.title))
        elif event in ("connect-failed", "auth-failed") and not self._log.opened:
            # Avoid remote-viewer's own modal error: end the process, we report it.
            process.send_signal(signal.SIGTERM)

    def _on_exit(self, process, result, _data):
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if process is not self._process:
            return
        self._read_log(process)
        if self._partial:
            self._on_line(process, self._partial)
            self._partial = ""
        self._close_log()
        # A SIGTERM we sent after a connection error is not a crash.
        self._exit_ok = process.get_successful() or (
            process.get_if_signaled() and process.get_term_sig() == signal.SIGTERM)
        viewer_log = self._log
        self._process = None
        self._remove_temp()
        if self._user_ending:
            self.manager.remove(self)
            return
        outcome = viewer_log.outcome(self._exit_ok)
        log.info("session %s ended: %s", self.id, outcome.value)
        self._handle(outcome, viewer_log)

    # Deciding what happens next

    def _handle(self, outcome: Outcome, viewer_log: ViewerLog) -> None:
        was_connected = viewer_log.opened
        if was_connected and self._opened_at and time.monotonic() - self._opened_at >= self.manager.policy.stable_after:
            self.attempt = 0
        reconnecting = self.attempt > 0

        if outcome == Outcome.USER_CLOSED:
            self.manager.remove(self)
            return
        if outcome == Outcome.DROPPED and time.monotonic() < self._expect_end_until:
            self.manager.remove(self)  # the user shut the VM down from here
            return

        if outcome == Outcome.AUTH_FAILED:
            if self.ref and self.server:
                message = _("The server rejected the ticket. Try connecting again.")
            else:
                message = (_("The ticket has expired or is invalid: a connection file can be used only once. Download a new file and try again."))
            self._end(EndKind.ERROR, message, alert=not reconnecting and not was_connected)
            return

        if outcome == Outcome.CONNECT_FAILED and not reconnecting:
            detail = viewer_log.connect_failed or ""
            self._end(EndKind.ERROR, _("Can’t connect to the virtual machine. {details}").format(details=detail).strip(), alert=True)
            return

        if outcome == Outcome.CRASHED and not reconnecting:
            self._end(EndKind.ERROR, _("remote-viewer quit unexpectedly."), alert=True)
            return

        # A dropped connection (or a failed reconnection attempt).
        if not self.ref:
            self._end(EndKind.ONE_TIME_TICKET,
                      _("Connection lost. The connection file’s ticket works only once: open a new one to reconnect."))
            return
        if not self.server:
            self._end(EndKind.NO_API,
                      _("Connection lost. Reconnecting needs a new ticket: add this server in the Proxmox preferences so the program can reconnect by itself."))
            return
        if not self.manager.settings.reconnect_automatically and not reconnecting:
            self._check_vm_then_end()
            return
        self._schedule_attempt()

    def _schedule_attempt(self) -> None:
        self.attempt += 1
        delay = self.manager.policy.delay(self.attempt)
        if delay is None:
            self._end(EndKind.GAVE_UP, _("Reconnecting failed after several attempts."))
            return
        self.retry_at = time.monotonic() + delay
        self.waiting_for_network = False
        self._set_state(State.RECONNECTING)
        if self.attempt == 1:
            self.manager.notify(self, _("Connection lost"), _("Reconnecting to {title}…").format(title=self.title))
        self._cancel_timer()
        self._timer = GLib.timeout_add(int(delay * 1000), self._attempt_now)

    def _attempt_now(self) -> bool:
        self._timer = None
        self.retry_at = None
        if not Gio.NetworkMonitor.get_default().get_network_available():
            self.waiting_for_network = True
            self._set_state(State.RECONNECTING)
            if self._network_handler is None:
                self._network_handler = Gio.NetworkMonitor.get_default().connect(
                    "network-changed", self._on_network_changed)
            return False
        self.waiting_for_network = False
        self._set_state(State.RECONNECTING)
        server, ref = self.server, self.ref
        if server is None or ref is None:
            self._handle(Outcome.DROPPED, ViewerLog())
            return False

        def work():
            client = self.manager.store.client(server)
            status = client.status(ref.node, ref.vmid)
            if status != "running":
                return ("not-running", status)
            try:
                return ("ok", client.spice_proxy(ref.node, ref.vmid))
            except ProxmoxError:
                # The VM may have stopped meanwhile (guest shutdown).
                if client.status(ref.node, ref.vmid) != "running":
                    return ("not-running", "stopped")
                raise

        run_in_thread(work, self._attempt_done)
        return False

    def _on_network_changed(self, monitor, available):
        if available and self.waiting_for_network and self.state == State.RECONNECTING:
            self._disconnect_network()
            self._attempt_now()

    def _disconnect_network(self):
        if self._network_handler is not None:
            Gio.NetworkMonitor.get_default().disconnect(self._network_handler)
            self._network_handler = None

    def _attempt_done(self, result, error) -> None:
        if self.state != State.RECONNECTING:
            return  # cancelled meanwhile
        if error is not None:
            if isinstance(error, (Unauthorized, Forbidden)):
                self._end(EndKind.ERROR, error_text(error))
            else:
                log.info("reconnect attempt %s failed: %s", self.attempt, error)
                self._schedule_attempt()
            return
        kind, payload = result
        if kind == "not-running":
            if time.monotonic() < self._expect_end_until:
                self.manager.remove(self)
            else:
                self._end(EndKind.VM_NOT_RUNNING, _("The virtual machine is off."))
            return
        values = vvfile.from_proxmox_json(payload)
        self.manager.store.learn_ca(values)
        self.launch(values)

    def _check_vm_then_end(self) -> None:
        """Automatic reconnection is off: tell whether the VM is still on."""
        server, ref = self.server, self.ref

        def work():
            return self.manager.store.client(server).status(ref.node, ref.vmid)

        def done(status, error):
            if status is not None and status != "running":
                self._end(EndKind.VM_NOT_RUNNING, _("The virtual machine is off."))
            else:
                self._end(EndKind.DROPPED, _("Connection lost."))

        run_in_thread(work, done)

    # User actions

    def reconnect_now(self) -> None:
        if self._process is not None:
            return
        if self.state == State.ENDED:
            self.attempt = 0
            self.end_kind = self.end_message = None
            if not (self.ref and self.server):
                return
            self.attempt = 1
        self._cancel_timer()
        self._set_state(State.RECONNECTING)
        self._attempt_now()

    def cancel_reconnect(self) -> None:
        self._cancel_timer()
        self._disconnect_network()
        self._end(EndKind.CANCELLED, _("Reconnection cancelled."))

    def disconnect(self) -> None:
        if self._process is not None:
            self._user_ending = True
            self._process.send_signal(signal.SIGTERM)
        else:
            self.manager.remove(self)

    def start_and_reconnect(self) -> None:
        server, ref = self.server, self.ref
        if not server or not ref or self.busy:
            return
        self.busy = True
        self._expect_end_until = 0
        self.end_message = _("Starting the virtual machine…")
        self.manager.changed(self)

        def work():
            client = self.manager.store.client(server)
            status = client.status(ref.node, ref.vmid)
            if status in ("paused", "suspended"):
                client.perform(PowerAction.RESUME, ref.node, ref.vmid)
            elif status != "running":
                client.perform(PowerAction.START, ref.node, ref.vmid)
            client.wait_until_running(ref.node, ref.vmid)
            return client.spice_proxy(ref.node, ref.vmid)

        def done(payload, error):
            self.busy = False
            if error is not None:
                self._end(EndKind.VM_NOT_RUNNING, error_text(error))
                return
            self.attempt = 0
            self.end_kind = self.end_message = None
            values = vvfile.from_proxmox_json(payload)
            self.manager.store.learn_ca(values)
            self.launch(values)

        run_in_thread(work, done)

    # Helpers

    def _end(self, kind: EndKind, message: str, alert: bool = False) -> None:
        self._cancel_timer()
        self._disconnect_network()
        self.end_kind = kind
        self.end_message = message
        self.retry_at = None
        self.waiting_for_network = False
        self._set_state(State.ENDED)
        if alert:
            self.manager.alert(self, message)
        elif kind != EndKind.CANCELLED:
            self.manager.notify(self, _("{title}: session ended").format(title=self.title), message, ended=True)

    def _set_state(self, state: State) -> None:
        self.state = state
        self.manager.changed(self)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def shutdown(self) -> None:
        """App quit (or session removed): leave remote-viewer windows open, just clean up.
        The viewer log is unlinked; a remote-viewer left running keeps its open handle."""
        self._cancel_timer()
        self._disconnect_network()
        self._close_log()
        self._remove_temp()


def _runtime_dir() -> str:
    directory = os.path.join(GLib.get_user_runtime_dir(), APP_SLUG)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    return directory


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        log.warning("cannot remove %s: %s", path, error)


class SessionManager:
    def __init__(self, store, settings, ui):
        self.store = store
        self.settings = settings
        self.ui = ui  # app: notify(), alert(), sessions_changed()
        self.policy = ReconnectPolicy()
        self.sessions: list[Session] = []

    @staticmethod
    def remote_viewer_available() -> bool:
        return shutil.which(REMOTE_VIEWER) is not None

    def session_for(self, ref: VMRef | None) -> Session | None:
        if ref is None:
            return None
        for session in self.sessions:
            if session.ref and session.ref.node == ref.node and session.ref.vmid == ref.vmid \
                    and session.ref.api_host.lower() == ref.api_host.lower():
                return session
        return None

    def open_values(self, values: dict[str, str], path: str | None = None, ref: VMRef | None = None,
                    vm_name: str | None = None) -> Session:
        ref = ref or vvfile.proxmox_ref(values)
        existing = self.session_for(ref)
        if existing is not None:
            if existing.is_active:
                existing.disconnect()
            else:
                self.remove(existing)
        session = Session(self, vvfile.display_title(values), ref, vm_name)
        self.sessions.append(session)
        self.ui.sessions_changed()
        session.launch(values, path)
        return session

    def open_file(self, path: str) -> Session:
        values = vvfile.read(path)  # raises VVFileError
        return self.open_values(values, path=path)

    def changed(self, session: Session) -> None:
        self.ui.sessions_changed()

    def remove(self, session: Session) -> None:
        session.shutdown()
        if session in self.sessions:
            self.sessions.remove(session)
        self.ui.sessions_changed()

    def notify(self, session: Session, title: str, body: str, ended: bool = False) -> None:
        self.ui.notify(session, title, body, ended)

    def alert(self, session: Session, message: str) -> None:
        self.ui.alert(session, message)

    def shutdown(self) -> None:
        for session in self.sessions:
            session.shutdown()
