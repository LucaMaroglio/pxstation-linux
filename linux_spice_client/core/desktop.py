"""Desktop integration: the .desktop entry and the .vv file association."""

from __future__ import annotations

from gi.repository import Gio, GLib

from .. import APP_ID
from .i18n import _

DESKTOP_ID = f"{APP_ID}.desktop"
VV_MIME = "application/x-virt-viewer"


def _app_info():
    try:
        return Gio.DesktopAppInfo.new(DESKTOP_ID)
    except TypeError:
        return None


def is_installed() -> bool:
    return _app_info() is not None


def _default():
    return Gio.AppInfo.get_default_for_type(VV_MIME, False)


def is_default_vv_handler() -> bool:
    default = _default()
    return default is not None and default.get_id() == DESKTOP_ID


def default_vv_handler_name() -> str | None:
    default = _default()
    return default.get_display_name() if default else None


def make_default_vv_handler() -> str | None:
    """Returns an error message, or None."""
    info = _app_info()
    if info is None:
        return _("The program isn’t installed: run install.sh first.")
    try:
        info.set_as_default_for_type(VV_MIME)
    except GLib.Error as error:
        return error.message
    return None
