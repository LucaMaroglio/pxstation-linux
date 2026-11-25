"""Minimal Proxmox VE REST client (API token auth): VM list, power actions and SPICE
connection files. Port of the macOS client's ``ProxmoxClient``.

TLS: the certificate must validate against the system trust store or the cluster CA
learned from a connection file (hostname checked), or match a SHA-256 fingerprint the
user explicitly pinned. There is no way to skip verification.
"""

from __future__ import annotations

import enum
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from urllib.parse import urlencode
from .i18n import _

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT = 15


# MARK: Errors


class ProxmoxError(Exception):
    """Base class; ``str(error)`` is a user-facing Italian message."""


class UntrustedCertificate(ProxmoxError):
    def __init__(self, sha256: str):
        self.sha256 = sha256
        super().__init__(_("The server’s certificate isn’t trusted (SHA-256 {fingerprint}).").format(fingerprint=format_fingerprint(sha256)))


class Unauthorized(ProxmoxError):
    def __init__(self):
        super().__init__(_("Proxmox rejected the API token. Check the token ID and secret."))


class Forbidden(ProxmoxError):
    def __init__(self, message: str):
        super().__init__(
            _("The API token isn’t allowed to do this ({message}). It needs VM.Audit, VM.PowerMgmt and VM.Console on the VM.").format(message=message)
        )


class HTTPError(ProxmoxError):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        suffix = f": {message}" if message else ""
        super().__init__(_("Proxmox returned HTTP {status}{details}.").format(status=status, details=suffix))


class InvalidResponse(ProxmoxError):
    def __init__(self):
        super().__init__(_("Proxmox sent an unexpected response."))


class InvalidConfiguration(ProxmoxError):
    def __init__(self, reason: str):
        super().__init__(_("The Proxmox server settings are invalid ({reason}).").format(reason=reason))


class TransportError(ProxmoxError):
    def __init__(self, reason: str):
        super().__init__(_("Couldn’t reach the Proxmox server ({reason}).").format(reason=reason))


class QemuNotResponding(ProxmoxError):
    def __init__(self, vmid: int):
        super().__init__(
            _("VM {vmid} didn’t answer Proxmox in time when asked for its SPICE details. Make sure its Display is set to SPICE and it isn’t busy with a backup or snapshot, then try again.").format(vmid=vmid)
        )


def format_fingerprint(hex_digest: str) -> str:
    text = hex_digest.upper()
    return ":".join(text[i:i + 2] for i in range(0, len(text), 2))


# MARK: Models

_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-_.@!]+$")
_HOSTNAME_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9\-_.]*[A-Za-z0-9])?$")
_NODE_RE = re.compile(r"^[A-Za-z0-9\-_.]+$")


def is_valid_token_id(text: str) -> bool:
    """``user@realm!name``: letters, digits and ``-_.@!`` only (it goes into a header)."""
    parts = text.split("!")
    return (
        len(parts) == 2 and "@" in parts[0] and bool(parts[1]) and len(text) <= 256
        and bool(_TOKEN_RE.match(text))
    )


def is_valid_secret(text: str) -> bool:
    """Token secrets are UUIDs."""
    try:
        uuid.UUID(text)
    except ValueError:
        return False
    return len(text) == 36


def bare_host(host: str) -> str:
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def is_valid_host(host: str) -> bool:
    host = bare_host(host.strip())
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(host))


@dataclass
class ProxmoxServer:
    """A Proxmox VE server. The token secret is not part of this value (keyring)."""

    name: str
    host: str
    token_id: str
    port: int = 8006
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    pinned_sha256: str | None = None
    cluster_ca_pem: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProxmoxServer":
        known = {k: data[k] for k in ("name", "host", "token_id", "port", "id", "pinned_sha256", "cluster_ca_pem") if k in data}
        return cls(**known)

    def copy(self, **changes) -> "ProxmoxServer":
        return replace(self, **changes)


STATUS_LABELS = {
    "running": "running",
    "stopped": "stopped",
    "paused": "paused",
    "suspended": "suspended",
    "prelaunch": "starting",
    "unknown": "unknown",
}


@dataclass
class ProxmoxVM:
    vmid: int
    name: str
    node: str
    status: str

    @property
    def key(self) -> str:
        return f"{self.node}/{self.vmid}"

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def is_paused(self) -> bool:
        return self.status in ("paused", "suspended")

    @property
    def status_label(self) -> str:
        return _(STATUS_LABELS[self.status]) if self.status in STATUS_LABELS else self.status


class PowerAction(enum.Enum):
    START = "start"
    SHUTDOWN = "shutdown"
    REBOOT = "reboot"
    RESET = "reset"
    STOP = "stop"
    SUSPEND = "suspend"
    RESUME = "resume"

    @property
    def is_destructive(self) -> bool:
        """Cuts the guest off without asking it: confirm first."""
        return self in (PowerAction.RESET, PowerAction.STOP)

    @property
    def title(self) -> str:
        return {
            PowerAction.START: _("Start"),
            PowerAction.SHUTDOWN: _("Shut Down"),
            PowerAction.REBOOT: _("Reboot"),
            PowerAction.RESET: _("Reset…"),
            PowerAction.STOP: _("Force Power Off…"),
            PowerAction.SUSPEND: _("Pause"),
            PowerAction.RESUME: _("Resume"),
        }[self]

    @property
    def icon(self) -> str:
        return {
            PowerAction.START: "media-playback-start-symbolic",
            PowerAction.RESUME: "media-playback-start-symbolic",
            PowerAction.SHUTDOWN: "system-shutdown-symbolic",
            PowerAction.REBOOT: "view-refresh-symbolic",
            PowerAction.RESET: "edit-undo-symbolic",
            PowerAction.STOP: "media-playback-stop-symbolic",
            PowerAction.SUSPEND: "media-playback-pause-symbolic",
        }[self]


def power_actions_for(vm_status: str) -> list[PowerAction]:
    if vm_status == "running":
        return [PowerAction.SHUTDOWN, PowerAction.REBOOT, PowerAction.SUSPEND, PowerAction.RESET, PowerAction.STOP]
    if vm_status in ("paused", "suspended"):
        return [PowerAction.RESUME, PowerAction.STOP]
    return [PowerAction.START]


# MARK: Client


def is_qmp_timeout(message: str) -> bool:
    return "qmp command" in message and "timeout" in message


class ProxmoxClient:
    def __init__(self, server: ProxmoxServer, secret: str):
        if not is_valid_host(server.host) or not (1 <= int(server.port) <= 65535):
            raise InvalidConfiguration("host")
        if not is_valid_token_id(server.token_id) or not is_valid_secret(secret):
            raise InvalidConfiguration("token")
        self.server = server
        self._authorization = f"PVEAPIToken={server.token_id}={secret}"
        self._host = bare_host(server.host)
        self._pinned = server.pinned_sha256.lower() if server.pinned_sha256 else None

    # API

    def virtual_machines(self) -> list[ProxmoxVM]:
        """QEMU VMs (no templates) visible to the token, sorted by name."""
        data = self._request("GET", "cluster/resources", query={"type": "vm"})
        if not isinstance(data, list):
            raise InvalidResponse()
        vms = []
        for entry in data:
            if not isinstance(entry, dict) or entry.get("type") != "qemu" or entry.get("template", 0):
                continue
            vmid, node = entry.get("vmid"), entry.get("node")
            if not isinstance(vmid, int) or not isinstance(node, str):
                continue
            vms.append(ProxmoxVM(vmid=vmid, name=str(entry.get("name") or f"VM {vmid}"), node=node,
                                 status=str(entry.get("status") or "unknown")))
        vms.sort(key=lambda vm: (vm.name.casefold(), vm.vmid))
        return vms

    def with_detailed_states(self, vms: list[ProxmoxVM]) -> list[ProxmoxVM]:
        """Recognises paused VMs: one status call per running VM, 8 at a time."""
        running = [vm for vm in vms if vm.is_running]
        if not running:
            return vms

        def fetch(vm):
            try:
                return vm.key, self.status(vm.node, vm.vmid)
            except ProxmoxError:
                return vm.key, None

        with ThreadPoolExecutor(max_workers=8) as pool:
            states = dict(pool.map(fetch, running))
        return [replace(vm, status=states.get(vm.key) or vm.status) for vm in vms]

    def status(self, node: str, vmid: int) -> str:
        """``running``, ``paused``, ``stopped``… (QMP status when available)."""
        data = self._request("GET", f"nodes/{_segment(node)}/qemu/{int(vmid)}/status/current")
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            raise InvalidResponse()
        if data["status"] == "running" and isinstance(data.get("qmpstatus"), str):
            return data["qmpstatus"]
        return data["status"]

    def perform(self, action: PowerAction, node: str, vmid: int) -> None:
        self._request("POST", f"nodes/{_segment(node)}/qemu/{int(vmid)}/status/{action.value}")

    def spice_proxy(self, node: str, vmid: int) -> dict:
        """A fresh SPICE connection (one-time ticket) as the web UI's SPICE button gets."""
        attempt = 0
        while True:
            try:
                data = self._request("POST", f"nodes/{_segment(node)}/qemu/{int(vmid)}/spiceproxy",
                                     form={"proxy": self._host})
                break
            except HTTPError as error:
                # QEMU's monitor was busy (backup, snapshot): usually fine on a second try.
                if error.status == 500 and is_qmp_timeout(error.message):
                    attempt += 1
                    if attempt >= 3:
                        raise QemuNotResponding(vmid) from error
                    time.sleep(2)
                    continue
                raise
        if not isinstance(data, dict):
            raise InvalidResponse()
        return data

    def wait_until_running(self, node: str, vmid: int, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status(node, vmid) == "running":
                return
            time.sleep(1)
        raise ProxmoxError(_("The VM didn’t start within a minute."))

    # Transport

    def _context(self, verify: bool) -> ssl.SSLContext:
        if not verify:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            context = ssl.create_default_context()
            if self.server.cluster_ca_pem:
                try:
                    # Cluster CA *in addition to* the system roots (ACME keeps working).
                    context.load_verify_locations(cadata=self.server.cluster_ca_pem)
                except ssl.SSLError:
                    pass
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context

    def _open(self) -> http.client.HTTPSConnection:
        port = int(self.server.port)
        connection = http.client.HTTPSConnection(self._host, port, context=self._context(True), timeout=TIMEOUT)
        try:
            connection.connect()
            return connection
        except ssl.SSLCertVerificationError:
            connection.close()
        except (OSError, ssl.SSLError) as error:
            connection.close()
            raise TransportError(_describe(error)) from error

        # Not trusted: accept only the exact certificate the user pinned.
        connection = http.client.HTTPSConnection(self._host, port, context=self._context(False), timeout=TIMEOUT)
        try:
            connection.connect()
        except (OSError, ssl.SSLError) as error:
            connection.close()
            raise TransportError(_describe(error)) from error
        der = connection.sock.getpeercert(binary_form=True)
        fingerprint = hashlib.sha256(der).hexdigest() if der else ""
        if self._pinned and fingerprint == self._pinned:
            return connection
        connection.close()
        raise UntrustedCertificate(fingerprint)

    def _request(self, method: str, path: str, query: dict | None = None, form: dict | None = None):
        target = "/api2/json/" + path
        if query:
            target += "?" + urlencode(query)
        headers = {"Authorization": self._authorization, "Accept": "application/json"}
        body = None
        if method == "POST":
            body = urlencode(form or {}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        connection = self._open()
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            length = response.getheader("Content-Length")
            if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                raise InvalidResponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise InvalidResponse()
            status = response.status
            reason = response.reason
        except (OSError, http.client.HTTPException) as error:
            raise TransportError(_describe(error)) from error
        finally:
            connection.close()

        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        if 200 <= status < 300:
            if not isinstance(payload, dict) or "data" not in payload:
                raise InvalidResponse()
            return payload["data"]
        message = _message(payload, reason)
        if status == 401:
            raise Unauthorized()
        if status == 403:
            raise Forbidden(message)
        raise HTTPError(status, message)


def _segment(text: str) -> str:
    """Node names are host names; refuse anything that could change the path."""
    if not text or not _NODE_RE.match(text):
        raise InvalidConfiguration(_("node name"))
    return text


def _message(payload, reason: str) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"][:200].strip()
    if isinstance(payload, dict) and isinstance(payload.get("errors"), dict):
        return "; ".join(f"{k}: {v}" for k, v in payload["errors"].items())[:200]
    return reason or ""


def _describe(error: BaseException) -> str:
    if isinstance(error, socket.timeout) or isinstance(error, TimeoutError):
        return _("timed out")
    if isinstance(error, socket.gaierror):
        return _("unknown host")
    if isinstance(error, ConnectionRefusedError):
        return _("connection refused")
    text = getattr(error, "strerror", None) or str(error)
    return text or error.__class__.__name__
