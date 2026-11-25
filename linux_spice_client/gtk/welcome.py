"""Shown when the program starts without Proxmox servers or a connection file."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from gi.repository import Gdk, Gtk

from .. import APP_NAME
from ..core import texts
from ..core.i18n import _


class WelcomeWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Welcome"), resizable=False)
        self.app = app
        self.set_icon_name(app.icon_name)
        header = Gtk.HeaderBar(show_close_button=True, title=APP_NAME)
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=36)
        box.set_size_request(440, -1)
        image = Gtk.Image.new_from_icon_name(app.icon_name, Gtk.IconSize.DIALOG)
        image.set_pixel_size(96)
        box.pack_start(image, False, False, 0)
        title = Gtk.Label()
        title.set_markup(f"<span size='x-large' weight='bold'>{APP_NAME}</span>")
        box.pack_start(title, False, False, 0)
        text = Gtk.Label(wrap=True, max_width_chars=48, justify=Gtk.Justification.CENTER,
                         label=texts.WELCOME)
        text.get_style_context().add_class("dim-label")
        box.pack_start(text, False, False, 0)

        open_button = Gtk.Button(label=_("Open Connection File…"), halign=Gtk.Align.CENTER)
        open_button.get_style_context().add_class("suggested-action")
        open_button.connect("clicked", lambda _b: app.controller.choose_and_open())
        box.pack_start(open_button, False, False, 0)
        vms = Gtk.Button(label=_("Virtual Machines…"), halign=Gtk.Align.CENTER)
        vms.connect("clicked", lambda _b: (app.show_vm_list(), self.destroy()))
        box.pack_start(vms, False, False, 0)
        hint = Gtk.Label(label=_("or drop a .vv file here"))
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        self.add(box)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        open_button.grab_focus()
        self.show_all()

    def _on_drop(self, _widget, _context, _x, _y, data, _info, _time):
        for uri in data.get_uris() or []:
            parsed = urlparse(uri)
            path = unquote(parsed.path)
            if parsed.scheme == "file" and path.lower().endswith(".vv"):
                self.app.controller.open_path(path)
