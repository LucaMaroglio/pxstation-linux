"""Preferences: General and Proxmox servers (port of the macOS ``SettingsView`` and
``ProxmoxSettingsView``/``ServerEditor``)."""

from __future__ import annotations

from gi.repository import GLib, Gtk, Pango

from ..core import desktop, texts
from ..core.controller import candidate_with_known_ca, test_connection
from ..core.proxmox import (ProxmoxServer, UntrustedCertificate, format_fingerprint, is_valid_host,
                            is_valid_secret, is_valid_token_id)
from ..core.util import error_text
from ..core.i18n import _


def _footnote(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=64)
    label.get_style_context().add_class("dim-label")
    return label


def _heading(text: str) -> Gtk.Label:
    label = Gtk.Label(xalign=0)
    label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    return label


class PreferencesWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title=_("Preferences"))
        self.app = app
        self.set_default_size(580, 520)
        self.set_icon_name(app.icon_name)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_custom_title(switcher)
        self.set_titlebar(header)

        self.stack.add_titled(self._general_page(), "general", _("General"))
        self.servers_page = ServersPage(app, self)
        self.stack.add_titled(self.servers_page, "proxmox", "Proxmox")
        self.add(self.stack)
        self.show_all()

    def show_page(self, page: str):
        self.stack.set_visible_child_name(page)

    def _switch(self, box, title, attribute, note=None, on_change=None):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label=title, xalign=0, wrap=True)
        row.pack_start(label, True, True, 0)
        switch = Gtk.Switch(active=getattr(self.app.settings, attribute), valign=Gtk.Align.CENTER)

        def changed(sw, _param):
            setattr(self.app.settings, attribute, sw.get_active())
            self.app.settings.save()
            if on_change:
                on_change()

        switch.connect("notify::active", changed)
        row.pack_start(switch, False, False, 0)
        box.pack_start(row, False, False, 0)
        if note:
            box.pack_start(_footnote(note), False, False, 0)

    def _general_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=20)

        box.pack_start(_heading(texts.LANGUAGE_HEADING), False, False, 0)
        combo = Gtk.ComboBoxText()
        for code, label in texts.language_choices():
            combo.append(code, label)
        combo.set_active_id(self.app.settings.language)
        box.pack_start(combo, False, False, 0)
        language_note = _footnote(texts.language_note(self.app.settings.language))
        box.pack_start(language_note, False, False, 0)

        def language_changed(widget):
            self.app.settings.language = widget.get_active_id() or ""
            self.app.settings.save()
            language_note.set_text(texts.language_note(self.app.settings.language))

        combo.connect("changed", language_changed)

        for heading, items in texts.GENERAL_SETTINGS:
            box.pack_start(_heading(heading), False, False, 6)
            for attribute, title, note in items:
                on_change = self.app.update_tray if attribute == "show_tray_icon" else None
                self._switch(box, title, attribute, note, on_change=on_change)

        box.pack_start(_heading(_("Connection files (.vv)")), False, False, 6)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.mime_label = Gtk.Label(xalign=0, wrap=True)
        row.pack_start(self.mime_label, True, True, 0)
        self.mime_button = Gtk.Button(label=_("Use This Program"))
        self.mime_button.connect("clicked", self._make_default)
        row.pack_start(self.mime_button, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(_footnote(texts.VV_FOOTNOTE), False, False, 0)
        self._update_mime()
        return box

    def _update_mime(self):
        is_default = desktop.is_default_vv_handler()
        self.mime_label.set_text(texts.vv_handler_text(is_default, desktop.default_vv_handler_name()))
        if is_default:
            self.mime_button.set_sensitive(False)
        else:
            self.mime_button.set_sensitive(desktop.is_installed())
            if not desktop.is_installed():
                self.mime_button.set_tooltip_text(_("Install the program with install.sh first."))

    def _make_default(self, _button):
        error = desktop.make_default_vv_handler()
        if error:
            self.app.message(_("Can’t change the file association"), error, parent=self)
        self._update_mime()


class ServersPage(Gtk.Box):
    def __init__(self, app, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=20)
        self.app = app
        self.window = window
        self.pack_start(_heading(_("Proxmox VE servers")), False, False, 0)

        frame = Gtk.Frame()
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        frame.add(self.listbox)
        self.pack_start(frame, False, False, 0)

        add = Gtk.Button(label=_("Add Server…"), halign=Gtk.Align.START)
        add.connect("clicked", lambda _b: self.edit(None))
        self.pack_start(add, False, False, 0)
        self.pack_start(_footnote(texts.SERVERS_FOOTNOTE), False, False, 0)

        app.store.connect_changed(self.refresh)
        self.connect("destroy", lambda _w: app.store.disconnect_changed(self.refresh))
        self.refresh()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        if not self.app.store.servers:
            row = Gtk.ListBoxRow(activatable=False)
            label = Gtk.Label(label=_("No servers yet."), xalign=0, margin=10)
            label.get_style_context().add_class("dim-label")
            row.add(label)
            self.listbox.add(row)
        for server in self.app.store.servers:
            row = Gtk.ListBoxRow(activatable=False)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin=8)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=server.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            detail = Gtk.Label(label=f"{server.token_id} · {server.host}:{server.port}", xalign=0,
                               ellipsize=Pango.EllipsizeMode.END)
            detail.get_style_context().add_class("dim-label")
            text_box.pack_start(name, False, False, 0)
            text_box.pack_start(detail, False, False, 0)
            box.pack_start(text_box, True, True, 0)
            edit = Gtk.Button(label=_("Edit…"))
            edit.connect("clicked", lambda _b, s=server: self.edit(s))
            box.pack_start(edit, False, False, 0)
            remove = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
            remove.set_tooltip_text(_("Remove the server and delete its token from the keyring"))
            remove.connect("clicked", lambda _b, s=server: self.remove(s))
            box.pack_start(remove, False, False, 0)
            row.add(box)
            self.listbox.add(row)
        self.listbox.show_all()

    def remove(self, server: ProxmoxServer):
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE, text=_("Remove “{name}”?").format(name=server.name))
        dialog.format_secondary_text(_("This server’s API token will be deleted from the keyring."))
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        button = dialog.add_button(_("Remove"), Gtk.ResponseType.OK)
        button.get_style_context().add_class("destructive-action")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.app.store.remove_server(server)

    def edit(self, server: ProxmoxServer | None, host: str | None = None):
        is_new = server is None
        if server is None:
            server = ProxmoxServer(name="", host=host or "", token_id="")
        ServerEditor(self.app, self.window, server, is_new).present()


class ServerEditor(Gtk.Dialog):
    """Add/edit dialog. Saving tests the connection; an untrusted certificate can be
    pinned after the user compares its fingerprint."""

    def __init__(self, app, parent, server: ProxmoxServer, is_new: bool):
        super().__init__(title=_("Add Server") if is_new else _("Edit Server"), transient_for=parent,
                         modal=True, use_header_bar=True)
        self.app = app
        self.server = server
        self.is_new = is_new
        self.untrusted: str | None = None
        self.working = False
        self.set_default_size(480, -1)

        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.save_button = self.add_button(_("Add") if is_new else _("Save"), Gtk.ResponseType.OK)
        self.save_button.get_style_context().add_class("suggested-action")
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(column_spacing=12, row_spacing=8, margin=18)
        self.name = self._entry(grid, 0, _("Name"), server.name, _("Office cluster"))
        self.host = self._entry(grid, 1, "Host", server.host, "pve1.esempio.it")
        self.port = self._entry(grid, 2, _("Port"), str(server.port), "8006")
        self.token = self._entry(grid, 3, _("Token ID"), server.token_id, "utente@pve!spice")
        self.secret = self._entry(grid, 4, _("Token secret"), "", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        self.secret.set_visibility(False)
        self.secret.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        if not is_new:
            self.secret.set_placeholder_text(_("leave empty to keep the saved one"))

        self.trust_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, no_show_all=True)
        self.trust_box.pack_start(Gtk.Label(
            label=texts.UNTRUSTED_CERT, xalign=0, wrap=True, max_width_chars=56), False, False, 0)
        self.fingerprint = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=56)
        self.fingerprint.get_style_context().add_class("monospace")
        self.trust_box.pack_start(self.fingerprint, False, False, 0)
        self.trust_box.pack_start(_footnote(texts.UNTRUSTED_CERT_HINT), False, False, 0)
        trust = Gtk.Button(label=_("Trust This Certificate"), halign=Gtk.Align.START)
        trust.connect("clicked", self._trust)
        self.trust_box.pack_start(trust, False, False, 0)
        grid.attach(self.trust_box, 0, 5, 2, 1)

        self.status = Gtk.Label(xalign=0, wrap=True, max_width_chars=56)
        self.status.get_style_context().add_class("dim-label")
        grid.attach(self.status, 0, 6, 2, 1)

        self.get_content_area().add(grid)
        for entry in (self.name, self.host, self.port, self.token, self.secret):
            entry.connect("changed", lambda _e: self._validate())
        self.connect("response", self._on_response)
        self._validate()
        self.show_all()

    @staticmethod
    def _entry(grid, row, title, text, placeholder) -> Gtk.Entry:
        label = Gtk.Label(label=title, xalign=1)
        label.get_style_context().add_class("dim-label")
        entry = Gtk.Entry(text=text or "", placeholder_text=placeholder, hexpand=True, activates_default=True)
        grid.attach(label, 0, row, 1, 1)
        grid.attach(entry, 1, row, 1, 1)
        return entry

    def _port(self) -> int | None:
        text = self.port.get_text().strip()
        if text.isdigit() and 1 <= int(text) <= 65535:
            return int(text)
        return None

    def _validate(self):
        secret = self.secret.get_text().strip()
        valid = (is_valid_host(self.host.get_text().strip()) and is_valid_token_id(self.token.get_text().strip())
                 and self._port() is not None
                 and (is_valid_secret(secret) if secret else not self.is_new))
        self.save_button.set_sensitive(valid and not self.working)

    def _on_response(self, _dialog, response):
        if response == Gtk.ResponseType.OK:
            self.stop_emission_by_name("response")
            self._test()
        else:
            self.destroy()

    def _trust(self, _button):
        if self.untrusted:
            self.server = self.server.copy(pinned_sha256=self.untrusted)
            self.untrusted = None
            self.trust_box.hide()
            self._test()

    def _test(self):
        """Lists VMs with the entered settings; saves only when that works."""
        if not self.save_button.get_sensitive() and not self.working:
            return
        host = self.host.get_text().strip()
        candidate = self.server.copy(
            name=self.name.get_text().strip() or host,
            host=host,
            port=self._port(),
            token_id=self.token.get_text().strip(),
        )
        candidate = candidate_with_known_ca(self.app.store, candidate)
        typed_secret = self.secret.get_text().strip()
        self.working = True
        self._validate()
        self.status.set_text(_("Connecting…"))

        def done(count, error):
            self.working = False
            self._validate()
            if isinstance(error, UntrustedCertificate):
                self.untrusted = error.sha256
                self.fingerprint.set_text(f"SHA-256: {format_fingerprint(error.sha256)}")
                self.trust_box.set_no_show_all(False)
                self.trust_box.show_all()
                self.status.set_text("")
                return
            if error is not None:
                self.status.set_text(error_text(error))
                return
            try:
                self.app.store.save_server(candidate, typed_secret or None)
            except Exception as save_error:
                self.status.set_text(error_text(save_error))
                return
            self.status.set_text(_("Connected: {count} virtual machines visible.").format(count=count))
            self.destroy()

        test_connection(self.app.store, candidate, typed_secret, done)
