""""Macchine virtuali" window: VMs of every configured Proxmox server, with power actions
and one-click connect (port of the macOS ``VMListView``)."""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk, Pango

from ..core.controller import Controller, VMListLoader
from ..core.proxmox import PowerAction, ProxmoxServer, ProxmoxVM, power_actions_for
from ..core.session import State
from ..core import texts
from ..core.texts import EMPTY_TOKEN_HINT, REFRESH_SECONDS, status_color
from ..core.util import error_text
from ..core.vvfile import VMRef
from ..core.i18n import _


def _dot(status: str) -> str:
    return f'<span foreground="{status_color(status)}">●</span>'


class VMRow(Gtk.ListBoxRow):
    def __init__(self, window: "VMListWindow", server: ProxmoxServer, vm: ProxmoxVM):
        super().__init__()
        self.window = window
        self.server = server
        self.vm = vm
        self.set_activatable(False)
        self.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=8)
        self.dot = Gtk.Label(use_markup=True)
        box.pack_start(self.dot, False, False, 0)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.name_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.caption = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.caption.get_style_context().add_class("dim-label")
        self.session_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, no_show_all=True)
        self.session_label.get_style_context().add_class("dim-label")
        texts.pack_start(self.name_label, False, False, 0)
        texts.pack_start(self.caption, False, False, 0)
        texts.pack_start(self.session_label, False, False, 0)
        box.pack_start(texts, True, True, 0)

        self.spinner = Gtk.Spinner(no_show_all=True)
        box.pack_start(self.spinner, False, False, 0)

        self.button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.button.connect("clicked", self._on_button)
        box.pack_start(self.button, False, False, 0)

        self.power = Gtk.MenuButton(valign=Gtk.Align.CENTER)
        self.power.set_image(Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.BUTTON))
        self.power.set_relief(Gtk.ReliefStyle.NONE)
        self.power.set_tooltip_text(_("Power"))
        box.pack_start(self.power, False, False, 0)
        self._menu_for: tuple | None = None

        events = Gtk.EventBox()
        events.add(box)
        events.connect("button-press-event", self._on_press)
        self.add(events)
        self.update(vm)

    @property
    def ref(self) -> VMRef:
        return VMRef(api_host=self.server.host, node=self.vm.node, vmid=self.vm.vmid)

    def update(self, vm: ProxmoxVM) -> None:
        self.vm = vm
        app = self.window.app
        busy = vm.key in self.window.busy
        session = app.sessions.session_for(self.ref)

        self.dot.set_markup(_dot(vm.status))
        self.dot.set_tooltip_text(vm.status_label)
        self.name_label.set_text(vm.name)
        self.caption.set_text(f"{vm.vmid} · {vm.node} · {vm.status_label}")

        if session is not None:
            self.session_label.set_text(_("Session: {status}").format(status=session.status_text()))
            self.session_label.set_tooltip_text(session.status_text())
            self.session_label.show()
        else:
            self.session_label.hide()

        if busy or (session is not None and session.busy):
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

        label, self._button_action = Controller.row_action(vm, session)
        self.button.set_label(label)
        self.button.set_tooltip_text(_("Opens {name} in a new window").format(name=vm.name) if self._button_action == "connect" else None)
        self.button.set_sensitive(not busy)
        self.power.set_sensitive(not busy)

        # Rebuild the menu only when its content changes (keeps an open menu open).
        menu_key = (vm.status,)
        if menu_key != self._menu_for:
            self._menu_for = menu_key
            self.power.set_popup(self._build_menu())

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        for action in power_actions_for(self.vm.status):
            item = Gtk.MenuItem(label=action.title)
            item.connect("activate", lambda _i, a=action: self.window.run_power(a, self.vm, self.server))
            menu.append(item)
        menu.show_all()
        return menu

    def _on_press(self, _widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY and self.power.get_sensitive():
            menu = self._build_menu()
            menu.attach_to_widget(self, None)
            menu.popup_at_pointer(event)
            return True
        return False

    def _on_button(self, _button):
        session = self.window.app.sessions.session_for(self.ref)
        if self._button_action == "disconnect" and session:
            session.disconnect()
        elif self._button_action == "cancel" and session:
            session.cancel_reconnect()
        else:
            self.window.connect_vm(self.vm, self.server)


class ServerSection(Gtk.Box):
    def __init__(self, window: "VMListWindow", server: ProxmoxServer):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window = window
        self.server = server
        self.rows: dict[str, VMRow] = {}

        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(server.name)}</b>")
        self.pack_start(title, False, False, 0)

        self.message = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, no_show_all=True)
        self.message_spinner = Gtk.Spinner(no_show_all=True)
        self.message_icon = Gtk.Image(no_show_all=True)
        self.message_label = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        self.message_label.get_style_context().add_class("dim-label")
        self.message.pack_start(self.message_spinner, False, False, 0)
        self.message.pack_start(self.message_icon, False, False, 0)
        self.message.pack_start(self.message_label, True, True, 0)
        self.pack_start(self.message, False, False, 0)

        frame = Gtk.Frame()
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.set_header_func(self._separator)
        frame.add(self.listbox)
        self.frame = frame
        self.pack_start(frame, False, False, 0)
        self.set_loading()

    @staticmethod
    def _separator(row, before):
        if before is not None and row.get_header() is None:
            row.set_header(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

    def _show_message(self, text: str, icon: str | None = None, spinning: bool = False):
        self.message_label.set_text(text)
        self.message_label.show()
        if spinning:
            self.message_spinner.show()
            self.message_spinner.start()
        else:
            self.message_spinner.stop()
            self.message_spinner.hide()
        if icon:
            self.message_icon.set_from_icon_name(icon, Gtk.IconSize.MENU)
            self.message_icon.show()
        else:
            self.message_icon.hide()
        self.message.show()

    def set_loading(self):
        self._show_message(_("Loading…"), spinning=True)
        self.frame.hide()

    def set_error(self, text: str):
        self._show_message(text, icon="dialog-warning-symbolic")
        self.frame.set_visible(bool(self.rows))

    def set_vms(self, vms: list[ProxmoxVM]):
        keys = [vm.key for vm in vms]
        if keys != list(self.rows):
            for row in self.rows.values():
                self.listbox.remove(row)
            self.rows = {}
            for vm in vms:
                row = VMRow(self.window, self.server, vm)
                self.rows[vm.key] = row
                self.listbox.add(row)
            self.listbox.show_all()
        else:
            for vm in vms:
                self.rows[vm.key].update(vm)
        if vms:
            self.message.hide()
            self.frame.show()
        else:
            self._show_message(EMPTY_TOKEN_HINT, icon="view-conceal-symbolic")
            self.frame.hide()

    def refresh_rows(self):
        for row in self.rows.values():
            row.update(row.vm)


class VMListWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Virtual Machines"))
        self.app = app
        self.busy: set[str] = set()
        self.sections: dict[str, ServerSection] = {}
        self.loader = VMListLoader(app.store, self._on_result,
                                   lambda loading: self.refresh_button.set_sensitive(not loading))
        self._timer = None
        self._tick = None
        self.set_default_size(620, 520)
        self.set_icon_name(app.icon_name)

        header = Gtk.HeaderBar(show_close_button=True, title=_("Virtual Machines"))
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_button.set_tooltip_text(_("Refresh (Ctrl+R)"))
        self.refresh_button.connect("clicked", lambda _b: self.reload())
        header.pack_start(self.refresh_button)
        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_button.set_menu_model(app.main_menu_model())
        header.pack_end(menu_button)
        self.set_titlebar(header)

        accel = Gtk.AccelGroup()
        accel.connect(Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK, 0, lambda *_: (self.reload(), True)[1])
        self.add_accel_group(accel)

        self.stack = Gtk.Stack()
        self.add(self.stack)

        # Empty state
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER,
                        halign=Gtk.Align.CENTER, margin=24)
        empty.pack_start(Gtk.Image.new_from_icon_name("network-server-symbolic", Gtk.IconSize.DIALOG), False, False, 0)
        title = Gtk.Label()
        title.set_markup(f"<big><b>{texts.NO_SERVERS_TITLE}</b></big>")
        empty.pack_start(title, False, False, 0)
        text = Gtk.Label(wrap=True, max_width_chars=50, justify=Gtk.Justification.CENTER,
                         label=texts.NO_SERVERS)
        text.get_style_context().add_class("dim-label")
        empty.pack_start(text, False, False, 0)
        settings_button = Gtk.Button(label=_("Open Preferences…"), halign=Gtk.Align.CENTER)
        settings_button.connect("clicked", lambda _b: app.show_preferences(page="proxmox"))
        empty.pack_start(settings_button, False, False, 0)
        self.stack.add_named(empty, "empty")

        # List
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.infobar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR, show_close_button=True, no_show_all=True)
        self.infobar_label = Gtk.Label(xalign=0, wrap=True)
        self.infobar.get_content_area().add(self.infobar_label)
        self.infobar.connect("response", lambda bar, _r: bar.hide())
        content.pack_start(self.infobar, False, False, 0)
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.sections_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=16)
        scrolled.add(self.sections_box)
        content.pack_start(scrolled, True, True, 0)
        self.stack.add_named(content, "list")

        app.store.connect_changed(self._on_servers_changed)
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("destroy", lambda _w: app.store.disconnect_changed(self._on_servers_changed))
        self.show_all()  # before choosing the stack page: a Stack ignores hidden children
        self._rebuild_sections()

    # Servers

    def _on_servers_changed(self):
        self._rebuild_sections()
        if self.get_mapped():
            self.reload()

    def _rebuild_sections(self):
        servers = self.app.store.servers
        ids = [server.id for server in servers]
        if ids != list(self.sections) or any(self.sections[s.id].server != s for s in servers):
            for section in self.sections.values():
                self.sections_box.remove(section)
            self.sections = {}
            for server in servers:
                section = ServerSection(self, server)
                self.sections[server.id] = section
                self.sections_box.pack_start(section, False, False, 0)
            self.sections_box.show_all()
            for section in self.sections.values():
                section.set_loading()
        self.stack.set_visible_child_name("list" if servers else "empty")

    # Refreshing

    def _on_map(self, _w):
        self.reload()
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(REFRESH_SECONDS, lambda: (self.reload(), True)[1])
        if self._tick is None:
            self._tick = GLib.timeout_add_seconds(1, self._on_tick)

    def _on_unmap(self, _w):
        for source in (self._timer, self._tick):
            if source is not None:
                GLib.source_remove(source)
        self._timer = self._tick = None

    def _on_tick(self):
        if any(s.state == State.RECONNECTING for s in self.app.sessions.sessions):
            self.sessions_changed()
        return True

    def sessions_changed(self):
        for section in self.sections.values():
            section.refresh_rows()

    def reload(self):
        self.loader.reload()

    def _on_result(self, server_id, vms=None, error=None):
        section = self.sections.get(server_id)
        if section is not None:
            if error is not None:
                section.set_error(error)
            else:
                section.set_vms(vms)

    # Actions

    def show_action_error(self, text: str | None):
        if text:
            self.infobar_label.set_text(text)
            self.infobar_label.show()
            self.infobar.show()
        else:
            self.infobar.hide()

    def _set_busy(self, vm: ProxmoxVM, busy: bool):
        if busy:
            self.busy.add(vm.key)
        else:
            self.busy.discard(vm.key)
        self.sessions_changed()

    def connect_vm(self, vm: ProxmoxVM, server: ProxmoxServer):
        self._set_busy(vm, True)
        self.show_action_error(None)

        def done(error):
            self._set_busy(vm, False)
            if error is not None:
                self.show_action_error(f"{vm.name}: {error_text(error)}")
            self.reload()

        self.app.controller.connect_vm(server, vm, done)

    def run_power(self, action: PowerAction, vm: ProxmoxVM, server: ProxmoxServer):
        if not self.app.controller.confirm_power(action, vm.name):
            return
        self._set_busy(vm, True)
        self.show_action_error(None)

        def done(error):
            self._set_busy(vm, False)
            if error is not None:
                self.show_action_error(f"{vm.name}: {error_text(error)}")
            self.reload()

        self.app.controller.power(server, VMRef(server.host, vm.node, vm.vmid), action, done)
