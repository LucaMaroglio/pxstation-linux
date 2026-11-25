"""Persistent settings and Proxmox servers (port of ``AppSettings`` + ``ProxmoxStore``).

Files live in ``$XDG_CONFIG_HOME/pxstation-linux`` (mode 0600); token secrets live in
the keyring. Mutations happen on the GTK main thread; workers get copies.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass

from gi.repository import GLib

from .. import APP_SLUG
from . import keyring_store
from .proxmox import InvalidConfiguration, ProxmoxClient, ProxmoxServer
from .vvfile import VMRef, proxmox_ref
from .i18n import _

log = logging.getLogger(__name__)


OLD_SLUG = "linux-spice-client"  # settings folder of the versions before PxStation Linux


def config_dir() -> str:
    path = os.path.join(GLib.get_user_config_dir(), APP_SLUG)
    if not os.path.exists(path):
        old = os.path.join(GLib.get_user_config_dir(), OLD_SLUG)
        if os.path.isdir(old):
            try:
                shutil.copytree(old, path)  # servers and settings carry over; tokens stay in the keyring
            except OSError as error:
                log.warning("Cannot copy the old settings from %s: %s", old, error)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _load(name: str, default):
    try:
        with open(os.path.join(config_dir(), name), encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as error:
        log.warning("Cannot read %s: %s", name, error)
        return default


def _save(name: str, data) -> None:
    directory = config_dir()
    fd, temp = tempfile.mkstemp(dir=directory, prefix=f".{name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.chmod(temp, 0o600)
        os.replace(temp, os.path.join(directory, name))
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


@dataclass
class Settings:
    reconnect_automatically: bool = True
    open_full_screen: bool = False
    show_tray_icon: bool = True
    notifications: bool = True
    language: str = ""  # interface language code, "" = system default (see core.i18n)

    @classmethod
    def load(cls) -> "Settings":
        data = _load("settings.json", {})
        defaults = cls()
        known = {k: v for k, v in data.items()
                 if k in cls.__dataclass_fields__ and type(v) is type(getattr(defaults, k))}
        return cls(**known)

    def save(self) -> None:
        _save("settings.json", asdict(self))


class Store:
    """Proxmox servers the user added and the cluster CAs learned from them."""

    def __init__(self):
        self.servers: list[ProxmoxServer] = []
        for entry in _load("servers.json", []):
            try:
                self.servers.append(ProxmoxServer.from_dict(entry))
            except (TypeError, KeyError):
                continue
        self._learned_cas: dict[str, str] = _load("cluster-cas.json", {})
        self._listeners = []

    def connect_changed(self, callback) -> None:
        self._listeners.append(callback)

    def disconnect_changed(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _changed(self) -> None:
        for callback in list(self._listeners):
            callback()

    def _persist(self) -> None:
        _save("servers.json", [server.to_dict() for server in self.servers])

    # Servers

    def server_for_host(self, host: str) -> ProxmoxServer | None:
        host = host.lower().strip("[]")
        for server in self.servers:
            if server.host.lower().strip("[]") == host:
                return server
        return None

    def server_by_id(self, server_id: str) -> ProxmoxServer | None:
        return next((server for server in self.servers if server.id == server_id), None)

    def known_ca(self, host: str) -> str | None:
        return self._learned_cas.get(host.lower())

    def save_server(self, server: ProxmoxServer, secret: str | None) -> None:
        """Adds or replaces a server; ``secret`` (when given) goes to the keyring."""
        if server.cluster_ca_pem is None:
            server = server.copy(cluster_ca_pem=self._learned_cas.get(server.host.lower()))
        if secret:
            keyring_store.save(server.id, secret)
        for index, existing in enumerate(self.servers):
            if existing.id == server.id:
                self.servers[index] = server
                break
        else:
            self.servers.append(server)
        self._persist()
        self._changed()

    def remove_server(self, server: ProxmoxServer) -> None:
        keyring_store.delete(server.id)
        self.servers = [s for s in self.servers if s.id != server.id]
        self._persist()
        self._changed()

    @staticmethod
    def client(server: ProxmoxServer) -> ProxmoxClient:
        """Safe to call from worker threads (the keyring lookup may block)."""
        secret = keyring_store.lookup(server.id)
        if not secret:
            raise InvalidConfiguration(_("no API token secret saved"))
        return ProxmoxClient(server, secret)

    def learn_ca(self, values: dict[str, str]) -> None:
        """Remembers the cluster CA from a connection fetched over an already verified API
        connection (never from a downloaded file: that could plant a CA for the API host).
        Main thread only."""
        ref: VMRef | None = proxmox_ref(values)
        ca = values.get("ca")
        if not ref or not ca:
            return
        host = ref.api_host.lower()
        if self._learned_cas.get(host) == ca:
            return
        self._learned_cas[host] = ca
        _save("cluster-cas.json", self._learned_cas)
        server = self.server_for_host(host)
        if server and server.cluster_ca_pem != ca:
            self.save_server(server.copy(cluster_ca_pem=ca), None)
