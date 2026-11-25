"""Talking to an instance that is already running, over its org.freedesktop.Application
D-Bus interface (the one Gio.Application exports). Used by the desktop file's actions
(``--action=vm-list`` …): the running instance does the work, with the activation token of
the launch so that, on Wayland, its window may come to the front."""

from __future__ import annotations

import logging
import os

from gi.repository import Gio, GLib

from .. import APP_ID

log = logging.getLogger(__name__)

ACTIONS = ("vm-list", "open-file", "preferences", "about", "quit")
OBJECT_PATH = "/" + APP_ID.replace(".", "/")


def platform_data() -> dict[str, GLib.Variant]:
    """The launch's activation token / startup id, as Gio.Application passes them."""
    data = {}
    token = os.environ.get("XDG_ACTIVATION_TOKEN")
    if token:
        data["activation-token"] = GLib.Variant("s", token)
    startup_id = os.environ.get("DESKTOP_STARTUP_ID")
    if startup_id:
        data["desktop-startup-id"] = GLib.Variant("s", startup_id)
    return data


def activate_action(name: str) -> bool:
    """Runs ``name`` in the running instance. False when there is none."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        has_owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "NameHasOwner", GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"),
                                  Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        if not has_owner:
            return False
        # Fire and forget: the action may open a modal dialog (quit, open file), and the
        # running instance only replies once it closes.
        bus.call(APP_ID, OBJECT_PATH, "org.freedesktop.Application", "ActivateAction",
                 GLib.Variant("(sava{sv})", (name, [], platform_data())), None,
                 Gio.DBusCallFlags.NO_AUTO_START, -1, None, None, None)
        bus.flush_sync(None)
        return True
    except GLib.Error as error:
        log.warning("could not reach the running instance: %s", error.message)
        return False


def take_action_argument(argv: list[str]) -> tuple[list[str], str | None]:
    """Removes ``--action=NAME`` from argv. Unknown names are ignored."""
    action = None
    rest = []
    for arg in argv:
        if arg.startswith("--action="):
            name = arg.split("=", 1)[1]
            action = name if name in ACTIONS else action
        else:
            rest.append(arg)
    return rest, action
