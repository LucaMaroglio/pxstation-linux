"""GTK interface (Cinnamon): Gtk.Application, windows and the XApp status icon.
All logic lives in ``core.controller``; this module only draws."""

from __future__ import annotations

import os

import gi
from ..core.i18n import _

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("XApp", "1.0")
    from gi.repository import XApp  # noqa: E402
except (ValueError, ImportError):
    XApp = None

from .. import APP_ID, APP_NAME, APP_SLUG, COPYRIGHT, DATA_DIR, UPSTREAM_URL, VERSION  # noqa: E402
from ..core.controller import Controller, MenuEntry  # noqa: E402


class Application(Gtk.Application):
    def __init__(self, action: str | None = None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._pending_action = action  # from the desktop file (--action=…), run at first activation
        GLib.set_application_name(APP_NAME)
        self.icon_name = APP_SLUG
        self.controller: Controller | None = None
        self._vm_list = None
        self._preferences = None
        self._welcome = None
        self._tray = None
        self._tray_signature = None
        self._held = False

    # Shortcuts used by the windows
    @property
    def store(self):
        return self.controller.store

    @property
    def settings(self):
        return self.controller.settings

    @property
    def sessions(self):
        return self.controller.sessions

    # MARK: Lifecycle

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.IconTheme.get_default().append_search_path(os.path.join(DATA_DIR, "icons"))
        Gtk.Window.set_default_icon_name(self.icon_name)
        self.controller = Controller(self)

        for name, callback in (
            ("open-file", lambda *_: self.controller.choose_and_open()),
            ("vm-list", lambda *_: self.show_vm_list()),
            ("preferences", lambda *_: self.show_preferences()),
            ("about", lambda *_: self.show_about()),
            ("quit", lambda *_: self.controller.request_quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.open-file", ["<Control>o"])
        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("app.preferences", ["<Control>comma"])
        self.update_tray()

    def do_activate(self):
        action, self._pending_action = self._pending_action, None
        if action:
            self.activate_action(action, None)
        else:
            self.controller.activate()

    def do_open(self, files, _n_files, _hint):
        self.controller.open_paths([f.get_path() for f in files if f.get_path()])
        self._update_hold()

    def do_shutdown(self):
        if self.controller:
            self.controller.shutdown()
        Gtk.Application.do_shutdown(self)

    def _update_hold(self):
        want = bool(self.settings.show_tray_icon and self._tray is not None) or bool(self.sessions.sessions)
        if want and not self._held:
            self.hold()
            self._held = True
        elif not want and self._held:
            self._held = False
            self.release()

    # MARK: UserInterface

    def icon(self) -> str:
        info = Gtk.IconTheme.get_default().lookup_icon(self.icon_name, 48, 0)
        return info.get_filename() if info else self.icon_name

    def refresh(self):
        if self._vm_list is not None:
            self._vm_list.sessions_changed()
        self._refresh_tray_menu()
        self._update_hold()

    def show_vm_list(self):
        from .vmlist import VMListWindow
        if self._vm_list is None:
            self._vm_list = VMListWindow(self)
            self._vm_list.connect("destroy", lambda _w: setattr(self, "_vm_list", None))
        self._vm_list.present()
        self.close_welcome()  # the list replaces it (also when opened from the tray or a desktop action)

    def show_welcome(self):
        from .welcome import WelcomeWindow
        if self._welcome is None:
            self._welcome = WelcomeWindow(self)
            self._welcome.connect("destroy", lambda _w: setattr(self, "_welcome", None))
        self._welcome.present()

    def close_welcome(self):
        if self._welcome is not None:
            self._welcome.destroy()

    def show_preferences(self, page: str | None = None, add_host: str | None = None):
        from .preferences import PreferencesWindow
        if self._preferences is None:
            self._preferences = PreferencesWindow(self)
            self.add_window(self._preferences)
            self._preferences.connect("destroy", lambda _w: setattr(self, "_preferences", None))
        if page or add_host:
            self._preferences.show_page(page or "proxmox")
        self._preferences.present()
        if add_host and self.store.server_for_host(add_host) is None:
            self._preferences.servers_page.edit(None, host=add_host)

    def choose_file(self) -> str | None:
        dialog = Gtk.FileChooserNative(title=_("Open Connection File"), transient_for=self.get_active_window(),
                                       action=Gtk.FileChooserAction.OPEN, accept_label=_("Open"))
        file_filter = Gtk.FileFilter()
        file_filter.set_name(_("virt-viewer connection files (.vv)"))
        file_filter.add_pattern("*.vv")
        file_filter.add_mime_type("application/x-virt-viewer")
        dialog.add_filter(file_filter)
        path = dialog.get_filename() if dialog.run() == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        return path

    def message(self, title: str, text: str, error: bool = True, parent=None):
        parent = parent or self.get_active_window()
        dialog = Gtk.MessageDialog(transient_for=parent, modal=parent is not None,
                                   message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(text)
        dialog.set_icon_name(self.icon_name)
        self.add_window(dialog)  # keeps the program running while it is shown
        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.show()

    def confirm(self, title: str, text: str, accept: str) -> bool:
        dialog = Gtk.MessageDialog(transient_for=self.get_active_window(), modal=True,
                                   message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE, text=title)
        dialog.format_secondary_text(text)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        button = dialog.add_button(accept, Gtk.ResponseType.OK)
        button.get_style_context().add_class("destructive-action")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def ask_quit(self) -> str | None:
        dialog = Gtk.MessageDialog(transient_for=self.get_active_window(), modal=True,
                                   message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                   text=_("Close the open sessions too?"))
        dialog.format_secondary_text(
            _("If you leave them open, the remote-viewer windows stay active but without the power menu or automatic reconnection."))
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Leave Open"), Gtk.ResponseType.NO)
        dialog.add_button(_("Close Sessions"), Gtk.ResponseType.YES)
        response = dialog.run()
        dialog.destroy()
        return {Gtk.ResponseType.YES: "close", Gtk.ResponseType.NO: "leave"}.get(response)

    def quit_app(self):
        self.quit()

    # MARK: Other windows

    def show_about(self):
        dialog = Gtk.AboutDialog(
            transient_for=self.get_active_window(), modal=True, program_name=APP_NAME,
            version=_("Version {version}").format(version=VERSION), copyright=COPYRIGHT,
            logo_icon_name=self.icon_name, license_type=Gtk.License.MIT_X11,
        )
        # Secondary page (Credits button): this program is a fork.
        dialog.add_credit_section(_("Based on"), [_("macos-spice-client by Paweł Więcaszek (MIT license)"),
                                                  UPSTREAM_URL])
        dialog.run()
        dialog.destroy()

    def main_menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append(_("Open Connection File…"), "app.open-file")
        menu.append(_("Preferences"), "app.preferences")
        section = Gio.Menu()
        section.append(_("About"), "app.about")
        section.append(_("Quit"), "app.quit")
        menu.append_section(None, section)
        return menu

    # MARK: Tray icon (XApp: native on Cinnamon)

    def update_tray(self):
        want = bool(self.settings.show_tray_icon) and XApp is not None
        if want and self._tray is None:
            self._tray = XApp.StatusIcon()
            self._tray.set_name(APP_SLUG)
            self._tray.set_tooltip_text(APP_NAME)
            path = self.icon()
            installed = os.path.isabs(path) and not path.startswith(DATA_DIR)
            # From the source tree the applet can't see our icon by name: pass the file.
            self._tray.set_icon_name(self.icon_name if installed else path)
            self._tray.connect("activate", self._on_tray_activate)
            self._tray_signature = None
            self._refresh_tray_menu()
        elif not want and self._tray is not None:
            self._tray.set_visible(False)
            self._tray = None
        self._update_hold()

    def _on_tray_activate(self, _icon, button, _time):
        if button == 1:
            self.controller.activate()

    def _refresh_tray_menu(self):
        if self._tray is None:
            return
        signature = self.controller.tray_signature()
        if signature == self._tray_signature:
            return
        self._tray_signature = signature
        self._tray.set_primary_menu(None)
        self._tray.set_secondary_menu(build_menu(self.controller.tray_entries()))
        self._tray.set_tooltip_text(self.controller.tray_tooltip())


def build_menu(entries: list[MenuEntry]) -> Gtk.Menu:
    menu = Gtk.Menu()
    for entry in entries:
        if entry.separator:
            menu.append(Gtk.SeparatorMenuItem())
            continue
        item = Gtk.MenuItem(label=entry.label)
        item.set_sensitive(entry.sensitive)
        if entry.children:
            item.set_submenu(build_menu(entry.children))
        elif entry.callback is not None:
            item.connect("activate", lambda _i, c=entry.callback: c())
        menu.append(item)
    menu.show_all()
    return menu


def run(argv: list[str], action: str | None = None) -> int:
    return Application(action).run(argv)
