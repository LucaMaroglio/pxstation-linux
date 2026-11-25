"""Proxmox API token secrets in the desktop keyring through the Secret Service API:
GNOME Keyring on Cinnamon, KWallet on KDE Plasma. One item per server; secrets never go
to files or logs."""

from __future__ import annotations

import gi
from .i18n import _

gi.require_version("Secret", "1")
from gi.repository import Secret  # noqa: E402

from .. import APP_ID, APP_NAME  # noqa: E402
from .environment import is_kde  # noqa: E402

_SCHEMA = Secret.Schema.new(
    f"{APP_ID}.ProxmoxToken",
    Secret.SchemaFlags.NONE,
    {"server-id": Secret.SchemaAttributeType.STRING},
)


class KeyringError(Exception):
    pass


def unavailable_message() -> str:
    if is_kde():
        return (_("The keyring is not available. On KDE open System Settings › KWallet, enable the KWallet subsystem (with Secret Service integration) and try again."))
    return (_("The keyring is not available. Check that GNOME Keyring (gnome-keyring) is installed and running."))


def service_available() -> bool:
    try:
        return Secret.Service.get_sync(Secret.ServiceFlags.NONE, None) is not None
    except Exception:
        return False


def save(server_id: str, secret: str) -> None:
    try:
        ok = Secret.password_store_sync(
            _SCHEMA, {"server-id": server_id}, Secret.COLLECTION_DEFAULT,
            _("{name} – Proxmox API token").format(name=APP_NAME), secret, None,
        )
    except Exception as error:  # GLib.Error
        if not service_available():
            raise KeyringError(unavailable_message()) from error
        raise KeyringError(_("Keyring: {error}").format(error=getattr(error, "message", error))) from error
    if not ok:
        raise KeyringError(_("Keyring: the secret could not be saved."))


def lookup(server_id: str) -> str | None:
    """The secret, ``None`` when there is none; raises ``KeyringError`` when the keyring
    itself can't be reached (so the user gets a useful message)."""
    try:
        return Secret.password_lookup_sync(_SCHEMA, {"server-id": server_id}, None)
    except Exception as error:
        if not service_available():
            raise KeyringError(unavailable_message()) from error
        return None


def delete(server_id: str) -> None:
    try:
        Secret.password_clear_sync(_SCHEMA, {"server-id": server_id}, None)
    except Exception:
        pass
