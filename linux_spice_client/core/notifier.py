"""Desktop notifications (org.freedesktop.Notifications through libnotify): Cinnamon and
KDE Plasma both show them, with action buttons."""

from __future__ import annotations

import logging

import gi

gi.require_version("Notify", "0.7")
from gi.repository import GLib, Notify  # noqa: E402

from .. import APP_ID, APP_NAME  # noqa: E402

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, icon):
        """``icon`` returns an icon name or file path."""
        self._icon = icon
        self._notes: dict[object, Notify.Notification] = {}
        self.actions_supported = False
        self.available = False
        try:
            self.available = Notify.init(APP_NAME)
            if self.available:
                self.actions_supported = "actions" in (Notify.get_server_caps() or [])
        except GLib.Error as error:
            log.warning("notifications unavailable: %s", error.message)

    def show(self, key, title: str, body: str, actions=(), on_action=None) -> None:
        """Replaces the previous notification with the same ``key``. ``actions`` is a list of
        ``(id, label)``; ``on_action(id)`` runs on the main loop.

        A notification with actions never expires: Plasma closes expired notifications and
        their buttons stop working, so it stays until the user acts on it or until ``close``
        (the controller closes it as soon as the session changes state)."""
        if not self.available:
            return
        self.close(key)
        note = Notify.Notification.new(title, body, self._icon())
        note.set_hint("desktop-entry", GLib.Variant("s", APP_ID))
        if self.actions_supported and on_action is not None and actions:
            for action_id, label in actions:
                note.add_action(action_id, label, lambda _n, a, _d: on_action(a), None)
            note.set_timeout(Notify.EXPIRES_NEVER)
        note.connect("closed", lambda n: self._notes.get(key) is n and self._notes.pop(key, None))
        self._notes[key] = note
        try:
            note.show()
        except GLib.Error as error:
            log.warning("notification failed: %s", error.message)

    def close(self, key) -> None:
        previous = self._notes.pop(key, None)
        if previous is not None:
            try:
                previous.close()
            except GLib.Error:
                pass

    def shutdown(self) -> None:
        if self.available and Notify.is_initted():
            Notify.uninit()
