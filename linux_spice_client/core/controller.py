"""Everything the two interfaces share: opening connections, power actions, session
actions, notifications, the tray menu content and quitting.

An interface (``gtk.app.Application`` or ``qt.app.Application``) implements
``UserInterface`` and only draws: it never talks to Proxmox or remote-viewer itself.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .. import APP_NAME
from .notifier import Notifier
from .proxmox import PowerAction, ProxmoxServer, ProxmoxVM
from .session import EndKind, Session, SessionManager, State
from .store import Settings, Store
from .util import error_text, run_in_thread
from .vvfile import VMRef, VVFileError, from_proxmox_json
from .i18n import _

log = logging.getLogger(__name__)

SESSION_POWER_ACTIONS = [PowerAction.SHUTDOWN, PowerAction.REBOOT, PowerAction.SUSPEND, PowerAction.RESUME]
SESSION_DESTRUCTIVE_ACTIONS = [PowerAction.RESET, PowerAction.STOP]


class UserInterface(Protocol):
    def icon(self) -> str: ...                       # icon name or file path for notifications
    def show_vm_list(self) -> None: ...
    def show_welcome(self) -> None: ...
    def close_welcome(self) -> None: ...
    def show_preferences(self, page: str | None = None, add_host: str | None = None) -> None: ...
    def choose_file(self) -> str | None: ...
    def message(self, title: str, text: str, error: bool = True) -> None: ...
    def confirm(self, title: str, text: str, accept: str) -> bool: ...
    def ask_quit(self) -> str | None: ...            # "close", "leave" or None (cancel)
    def refresh(self) -> None: ...                   # sessions/servers changed
    def quit_app(self) -> None: ...


@dataclass
class MenuEntry:
    """Toolkit-neutral menu item (tray menu, session submenus)."""

    label: str = ""
    callback: Callable[[], None] | None = None
    sensitive: bool = True
    children: list["MenuEntry"] = field(default_factory=list)
    separator: bool = False

    @classmethod
    def sep(cls) -> "MenuEntry":
        return cls(separator=True)

    @classmethod
    def info(cls, label: str) -> "MenuEntry":
        return cls(label=label, sensitive=False)


class Controller:
    def __init__(self, ui: UserInterface):
        self.ui = ui
        self.store = Store()
        self.settings = Settings.load()
        self.sessions = SessionManager(self.store, self.settings, self)
        self.notifier = Notifier(ui.icon)
        self._ended_notes: set = set()
        self.store.connect_changed(self.ui.refresh)

    # MARK: Starting

    def activate(self) -> None:
        if self.store.servers:
            self.ui.show_vm_list()
        else:
            self.ui.show_welcome()

    def open_paths(self, paths: list[str]) -> None:
        for path in paths:
            self.open_path(path)

    def choose_and_open(self) -> None:
        path = self.ui.choose_file()
        if path:
            self.open_path(path)

    def check_viewer(self) -> bool:
        if SessionManager.remote_viewer_available():
            return True
        self.ui.message(_("remote-viewer is not installed"),
                        _("Install the virt-viewer package (sudo apt install virt-viewer) and try again."))
        return False

    def open_path(self, path: str) -> None:
        if not self.check_viewer():
            return
        try:
            self.sessions.open_file(path)
        except (OSError, VVFileError) as error:
            self.ui.message(_("Can’t open the connection file"), error_text(error))
            return
        self.ui.close_welcome()

    def connect_vm(self, server: ProxmoxServer, vm: ProxmoxVM, done: Callable) -> None:
        """Starts the VM if needed, fetches a fresh connection and opens a session.
        ``done(error)`` runs on the main loop."""
        if not self.check_viewer():
            done(None)
            return
        store = self.store

        def work():
            client = store.client(server)
            if not vm.is_running:
                wake = PowerAction.RESUME if vm.is_paused else PowerAction.START
                client.perform(wake, vm.node, vm.vmid)
                client.wait_until_running(vm.node, vm.vmid)
            return client.spice_proxy(vm.node, vm.vmid)

        def finished(payload, error):
            if error is None:
                values = from_proxmox_json(payload)
                self.store.learn_ca(values)
                self.sessions.open_values(values, ref=VMRef(server.host, vm.node, vm.vmid), vm_name=vm.name)
            done(error)

        run_in_thread(work, finished)

    @staticmethod
    def row_action(vm: ProxmoxVM, session: Session | None) -> tuple[str, str]:
        """Label and kind (``connect``, ``disconnect``, ``cancel``) of a VM row's button."""
        if session is not None and session.state in (State.CONNECTING, State.CONNECTED):
            return _("Disconnect"), "disconnect"
        if session is not None and session.state == State.RECONNECTING:
            return _("Cancel Reconnection"), "cancel"
        if vm.is_running:
            return _("Connect"), "connect"
        if vm.is_paused:
            return _("Resume & Connect"), "connect"
        return _("Start & Connect"), "connect"

    def session_for_vm(self, server: ProxmoxServer, vm: ProxmoxVM) -> Session | None:
        return self.sessions.session_for(VMRef(server.host, vm.node, vm.vmid))

    # MARK: Power

    def confirm_power(self, action: PowerAction, vm_name: str) -> bool:
        """Asks before actions that cut the guest off."""
        if not action.is_destructive:
            return True
        verb = _("Reset") if action == PowerAction.RESET else _("Force power off")
        return self.ui.confirm(
            _("{action} “{vm}”?").format(action=verb, vm=vm_name),
            _("This is like pulling the power cord: unsaved work in the virtual machine is lost. Use Shut Down or Reboot to let the guest close cleanly."),
            _("Reset") if action == PowerAction.RESET else _("Power Off"),
        )

    def power(self, server: ProxmoxServer, ref: VMRef, action: PowerAction, done: Callable | None = None) -> None:
        session = self.sessions.session_for(ref)
        if session is not None and action in (PowerAction.SHUTDOWN, PowerAction.STOP):
            session.expect_end()
        store = self.store

        def work():
            store.client(server).perform(action, ref.node, ref.vmid)
            time.sleep(2)

        def finished(_result, error):
            if done is not None:
                done(error)
            elif error is not None:
                self.ui.message(_("Power"), error_text(error))

        run_in_thread(work, finished)

    def session_power(self, session: Session, action: PowerAction) -> None:
        server = session.server
        if server is None or session.ref is None or not self.confirm_power(action, session.vm_name):
            return
        session.busy = True
        self.ui.refresh()

        def done(error):
            session.busy = False
            self.ui.refresh()
            if error is not None:
                self.ui.message(_("{title}: power").format(title=session.title), error_text(error))

        self.power(server, session.ref, action, done)

    # MARK: Session actions

    @staticmethod
    def session_actions(session: Session) -> list[tuple[str, str]]:
        """What an ended session offers (notification buttons and tray items)."""
        if session.state != State.ENDED:
            return []
        if session.end_kind == EndKind.VM_NOT_RUNNING and session.can_control_power:
            return [("start-reconnect", _("Start & Reconnect"))]
        if session.end_kind == EndKind.NO_API:
            return [("setup-proxmox", _("Set Up Proxmox Access…"))]
        if session.ref and session.server and session.end_kind != EndKind.VM_NOT_RUNNING:
            return [("reconnect", _("Reconnect"))]
        return []

    def run_session_action(self, session: Session, action_id: str) -> None:
        if session not in self.sessions.sessions:
            return
        if action_id == "start-reconnect":
            session.start_and_reconnect()
        elif action_id == "reconnect":
            session.reconnect_now()
        elif action_id == "setup-proxmox" and session.ref:
            self.ui.show_preferences(page="proxmox", add_host=session.ref.api_host)
        elif action_id == "cancel":
            session.cancel_reconnect()
        elif action_id == "disconnect":
            session.disconnect()
        elif action_id == "dismiss":
            self.sessions.remove(session)

    # MARK: SessionManager callbacks

    def sessions_changed(self) -> None:
        self._close_stale_notifications()
        self.ui.refresh()

    def _close_stale_notifications(self) -> None:
        """A "session ended" notification offers actions and never expires: close it once
        the session is gone or running again, so its buttons are never out of date."""
        current = {s.id: s for s in self.sessions.sessions}
        for session_id in list(self._ended_notes):
            session = current.get(session_id)
            if session is None or session.state is not State.ENDED:
                self.notifier.close(session_id)
                self._ended_notes.discard(session_id)

    def alert(self, session: Session, message: str) -> None:
        self.ui.message(session.title, message)

    def notify(self, session: Session, title: str, body: str, ended: bool = False) -> None:
        if not self.settings.notifications:
            return
        actions = self.session_actions(session) if ended else []
        if actions:
            self._ended_notes.add(session.id)
        else:
            self._ended_notes.discard(session.id)
        self.notifier.show(session.id, title, body, actions,
                           lambda action_id: self.run_session_action(session, action_id))

    # MARK: Tray menu

    def tray_signature(self) -> tuple:
        return (
            tuple((s.id, s.state, s.end_kind, s.attempt, s.busy, s.can_control_power, s.waiting_for_network)
                  for s in self.sessions.sessions),
            len(self.store.servers),
        )

    def tray_tooltip(self) -> str:
        active = sum(1 for s in self.sessions.sessions if s.is_active)
        return _("{name} — active sessions: {count}").format(name=APP_NAME, count=active) if active else APP_NAME

    @staticmethod
    def short_state(session: Session) -> str:
        if session.state == State.RECONNECTING:
            if session.waiting_for_network:
                return _("waiting for the network")
            return _("reconnecting {attempt}/{total}").format(attempt=session.attempt, total=session.max_attempts)
        return {State.CONNECTING: _("connecting…"), State.CONNECTED: _("connected")}.get(session.state, _("ended"))

    def tray_entries(self) -> list[MenuEntry]:
        entries: list[MenuEntry] = []
        if self.sessions.sessions:
            entries.append(MenuEntry.info(_("Sessions")))
            for session in self.sessions.sessions:
                entries.append(MenuEntry(f"{session.title} — {self.short_state(session)}",
                                         children=self.session_entries(session)))
            entries.append(MenuEntry.sep())
        entries += [
            MenuEntry(_("Virtual Machines…"), self.ui.show_vm_list),
            MenuEntry(_("Open Connection File…"), self.choose_and_open),
            MenuEntry(_("Preferences…"), self.ui.show_preferences),
            MenuEntry.sep(),
            MenuEntry(_("Quit"), self.request_quit),
        ]
        return entries

    def session_entries(self, session: Session) -> list[MenuEntry]:
        entries: list[MenuEntry] = []
        if session.state == State.ENDED and session.end_message:
            text = session.end_message
            entries.append(MenuEntry.info(text if len(text) < 80 else text[:77] + "…"))
        if session.state == State.RECONNECTING:
            entries.append(MenuEntry(_("Try Now"), session.reconnect_now))
            entries.append(MenuEntry(_("Cancel Reconnection"), session.cancel_reconnect))
        for action_id, label in self.session_actions(session):
            entries.append(MenuEntry(label, lambda a=action_id: self.run_session_action(session, a),
                                     sensitive=not session.busy))
        if session.can_control_power:
            power = []
            for group in (SESSION_POWER_ACTIONS, SESSION_DESTRUCTIVE_ACTIONS):
                if power:
                    power.append(MenuEntry.sep())
                power += [MenuEntry(a.title, lambda a=a: self.session_power(session, a)) for a in group]
            entries.append(MenuEntry(_("Power"), children=power, sensitive=not session.busy))
        elif session.ref is not None:
            host = session.ref.api_host
            entries.append(MenuEntry(_("Set Up Proxmox Access…"),
                                     lambda: self.ui.show_preferences(page="proxmox", add_host=host)))
        entries.append(MenuEntry.sep())
        if session.is_active:
            entries.append(MenuEntry(_("Disconnect"), session.disconnect))
        else:
            entries.append(MenuEntry(_("Remove from List"), lambda: self.sessions.remove(session)))
        return entries

    # MARK: Quitting

    def request_quit(self) -> None:
        active = [s for s in self.sessions.sessions if s.is_active]
        if active:
            choice = self.ui.ask_quit()
            if choice is None:
                return
            if choice == "close":
                for session in active:
                    session.disconnect()
        self.ui.quit_app()

    def shutdown(self) -> None:
        self.sessions.shutdown()
        self.notifier.shutdown()


class VMListLoader:
    """Loads the VMs of every server, one refresh at a time (a request during a refresh
    runs once more afterwards). ``on_result(server_id, vms=None, error=None)`` runs on the
    main loop, first with the plain list, then with paused states filled in."""

    def __init__(self, store: Store, on_result: Callable, on_loading: Callable[[bool], None]):
        self.store = store
        self.on_result = on_result
        self.on_loading = on_loading
        self.loading = False
        self._again = False

    def reload(self) -> None:
        if self.loading:
            self._again = True
            return
        servers = list(self.store.servers)
        if not servers:
            return
        self.loading = True
        self._again = False
        self.on_loading(True)
        store = self.store

        from gi.repository import GLib

        def post(server_id, vms=None, error=None):
            GLib.idle_add(lambda: (self.on_result(server_id, vms=vms, error=error), False)[1])

        def work():
            for server in servers:
                try:
                    client = store.client(server)
                    vms = client.virtual_machines()
                    post(server.id, vms=vms)
                    post(server.id, vms=client.with_detailed_states(vms))
                except Exception as error:
                    post(server.id, error=error_text(error))

        def done(_result, _error):
            self.loading = False
            self.on_loading(False)
            if self._again:
                self.reload()

        run_in_thread(work, done)


def test_connection(store: Store, candidate: ProxmoxServer, typed_secret: str, done: Callable) -> None:
    """Lists VMs with ``candidate``; ``done(count, error)`` on the main loop (server editor)."""
    from . import keyring_store
    from .proxmox import ProxmoxClient

    def work():
        secret = typed_secret or keyring_store.lookup(candidate.id) or ""
        return len(ProxmoxClient(candidate, secret).virtual_machines())

    run_in_thread(work, done)


def candidate_with_known_ca(store: Store, candidate: ProxmoxServer) -> ProxmoxServer:
    if candidate.cluster_ca_pem is None:
        known = store.server_for_host(candidate.host)
        candidate = candidate.copy(cluster_ca_pem=(known.cluster_ca_pem if known else None)
                                   or store.known_ca(candidate.host))
    return candidate
