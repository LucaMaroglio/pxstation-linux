"""File chooser through the XDG desktop portal (org.freedesktop.portal.FileChooser).

Used when the toolkit can't show the desktop's own dialog by itself, e.g. a Qt version that
Plasma doesn't integrate: the portal backend (xdg-desktop-portal-kde) draws KDE's dialog.
Gio only, no toolkit code.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

_BUS_NAME = "org.freedesktop.portal.Desktop"
_PATH = "/org/freedesktop/portal/desktop"


def open_file(parent: str, title: str, filters: list[tuple[str, list[str]]],
              done: Callable[[str | None], None]) -> bool:
    """Asks the portal for one local file. ``parent`` is the window identifier the portal
    expects ("x11:<hex xid>", "wayland:<handle>" or ""). ``filters`` is a list of
    ``(name, [glob, …])``. Returns False when no portal answers: the caller then uses its
    own dialog. Otherwise ``done(path or None)`` runs later on the main loop."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        log.info("no session bus: %s", error.message)
        return False
    token = "lsc" + secrets.token_hex(8)
    sender = bus.get_unique_name()[1:].replace(".", "_")
    request_path = f"{_PATH}/request/{sender}/{token}"
    state = {"subscription": 0, "finished": False}

    def finish(path: str | None):
        if state["finished"]:
            return
        state["finished"] = True
        if state["subscription"]:
            bus.signal_unsubscribe(state["subscription"])
        done(path)

    def on_response(_bus, _sender, _path, _iface, _signal, params, _data):
        response, results = params.unpack()
        uris = results.get("uris") or [] if response == 0 else []
        path = Gio.File.new_for_uri(uris[0]).get_path() if uris else None
        finish(path)

    # Subscribe before calling, so a fast answer can't be missed.
    state["subscription"] = bus.signal_subscribe(
        _BUS_NAME, "org.freedesktop.portal.Request", "Response", request_path, None,
        Gio.DBusSignalFlags.NO_MATCH_RULE, on_response, None)
    portal_filters = [(name, [(0, glob) for glob in globs]) for name, globs in filters]
    options = {
        "handle_token": GLib.Variant("s", token),
        "modal": GLib.Variant("b", True),
        "multiple": GLib.Variant("b", False),
    }
    if portal_filters:
        options["filters"] = GLib.Variant("a(sa(us))", portal_filters)
        options["current_filter"] = GLib.Variant("(sa(us))", portal_filters[0])
    try:
        bus.call_sync(_BUS_NAME, _PATH, "org.freedesktop.portal.FileChooser", "OpenFile",
                      GLib.Variant("(ssa{sv})", (parent, title, options)),
                      GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error as error:
        log.info("file chooser portal unavailable: %s", error.message)
        bus.signal_unsubscribe(state["subscription"])
        return False
    return True
