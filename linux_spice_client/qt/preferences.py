"""Preferences (Qt): General and Proxmox servers. Same options and texts as the GTK window,
laid out the KDE way (tabs, check boxes, a list with buttons beside it)."""

from __future__ import annotations

from .binding import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                      QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                      QSpinBox, QTabWidget, Qt, QVBoxLayout, QWidget)

from ..core import desktop, texts
from ..core.controller import candidate_with_known_ca, test_connection
from ..core.proxmox import (ProxmoxServer, UntrustedCertificate, format_fingerprint, is_valid_host,
                            is_valid_secret, is_valid_token_id)
from ..core.util import error_text
from .common import note, themed
from ..core.i18n import _


class PreferencesWindow(QDialog):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle(_("Configure PxStation Linux"))
        self.resize(640, 680)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(_scrollable(self._general_page()), themed("configure"), _("General"))
        self.servers_page = ServersPage(app, self)
        self.tabs.addTab(self.servers_page, themed("network-server"), "Proxmox")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def show_page(self, page: str):
        self.tabs.setCurrentIndex(1 if page == "proxmox" else 0)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.app.window_closed()

    def reject(self):  # Esc hides the dialog without a close event
        super().reject()
        self.app.window_closed()

    def _general_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox(texts.LANGUAGE_HEADING)
        group_layout = QVBoxLayout(group)
        combo = QComboBox()
        for code, label in texts.language_choices():
            combo.addItem(label, code)
        combo.setCurrentIndex(max(0, combo.findData(self.app.settings.language)))
        group_layout.addWidget(combo)
        language_note = note(texts.language_note(self.app.settings.language))
        group_layout.addWidget(language_note)

        def language_changed(index):
            self.app.settings.language = combo.itemData(index) or ""
            self.app.settings.save()
            language_note.setText(texts.language_note(self.app.settings.language))

        combo.currentIndexChanged.connect(language_changed)
        layout.addWidget(group)

        for heading, items in texts.GENERAL_SETTINGS:
            group = QGroupBox(heading)
            group_layout = QVBoxLayout(group)
            for attribute, title, text in items:
                box = QCheckBox(title)
                box.setChecked(getattr(self.app.settings, attribute))
                box.toggled.connect(lambda checked, a=attribute: self._set(a, checked))
                group_layout.addWidget(box)
                if text:
                    hint = note(text)
                    hint.setContentsMargins(24, 0, 0, 4)
                    group_layout.addWidget(hint)
            layout.addWidget(group)

        group = QGroupBox(_("Connection files (.vv)"))
        group_layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.mime_label = QLabel()
        self.mime_label.setWordWrap(True)
        row.addWidget(self.mime_label, 1)
        self.mime_button = QPushButton(_("Use This Program"))
        self.mime_button.clicked.connect(self._make_default)
        row.addWidget(self.mime_button)
        group_layout.addLayout(row)
        group_layout.addWidget(note(texts.VV_FOOTNOTE))
        layout.addWidget(group)
        layout.addStretch(1)
        self._update_mime()
        return page

    def _set(self, attribute: str, value: bool):
        setattr(self.app.settings, attribute, value)
        self.app.settings.save()
        if attribute == "show_tray_icon":
            self.app.update_tray()

    def _update_mime(self):
        is_default = desktop.is_default_vv_handler()
        self.mime_label.setText(texts.vv_handler_text(is_default, desktop.default_vv_handler_name()))
        installed = desktop.is_installed()
        self.mime_button.setEnabled(not is_default and installed)
        self.mime_button.setToolTip("" if installed else _("Install the program with install.sh first."))

    def _make_default(self):
        error = desktop.make_default_vv_handler()
        if error:
            self.app.message(_("Can’t change the file association"), error, parent=self)
        self._update_mime()


def _scrollable(page: QWidget) -> QScrollArea:
    """Tab pages don't pass word-wrapped labels the height they need for their width
    (QStackedWidget ignores height-for-width), so long notes got clipped with larger fonts.
    A resizable scroll area does honour it, and scrolls if the window is really too small."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


class ServersPage(QWidget):
    def __init__(self, app, window):
        super().__init__()
        self.app = app
        self.window = window
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        self.list.currentRowChanged.connect(lambda _r: self._update_buttons())
        row.addWidget(self.list, 1)
        buttons = QVBoxLayout()
        self.add_button = QPushButton(themed("list-add"), _("Add…"))
        self.add_button.clicked.connect(lambda: self.edit(None))
        self.edit_button = QPushButton(themed("document-edit"), _("Edit…"))
        self.edit_button.clicked.connect(self._edit_selected)
        self.remove_button = QPushButton(themed("list-remove"), _("Remove"))
        self.remove_button.clicked.connect(self._remove_selected)
        for button in (self.add_button, self.edit_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        row.addLayout(buttons)
        layout.addLayout(row)
        layout.addWidget(note(texts.SERVERS_FOOTNOTE))

        app.store.connect_changed(self.refresh)
        self.destroyed.connect(lambda: app.store.disconnect_changed(self.refresh))
        self.refresh()

    def refresh(self):
        self.list.clear()
        for server in self.app.store.servers:
            item = QListWidgetItem(themed("network-server"), f"{server.name}\n{server.token_id} · {server.host}:{server.port}")
            item.setData(Qt.ItemDataRole.UserRole, server.id)
            self.list.addItem(item)
        if not self.app.store.servers:
            item = QListWidgetItem(_("No servers yet."))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self._update_buttons()

    def _selected(self) -> ProxmoxServer | None:
        item = self.list.currentItem()
        server_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.app.store.server_by_id(server_id) if server_id else None

    def _update_buttons(self):
        selected = self._selected() is not None
        self.edit_button.setEnabled(selected)
        self.remove_button.setEnabled(selected)

    def _edit_selected(self):
        server = self._selected()
        if server:
            self.edit(server)

    def _remove_selected(self):
        server = self._selected()
        if server is None:
            return
        answer = QMessageBox.question(
            self.window, _("Remove Server"), _("Remove “{name}”?").format(name=server.name) + "\n\n" + _("This server’s API token will be deleted from the keyring."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.app.store.remove_server(server)

    def edit(self, server: ProxmoxServer | None, host: str | None = None):
        is_new = server is None
        if server is None:
            server = ProxmoxServer(name="", host=host or "", token_id="")
        ServerEditor(self.app, self.window, server, is_new).open()


class ServerEditor(QDialog):
    """Add/edit dialog. Saving tests the connection; an untrusted certificate can be
    pinned after the user compares its fingerprint."""

    def __init__(self, app, parent, server: ProxmoxServer, is_new: bool):
        super().__init__(parent)
        self.app = app
        self.server = server
        self.is_new = is_new
        self.untrusted: str | None = None
        self.working = False
        self.setWindowTitle(_("Add Server") if is_new else _("Edit Server"))
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(server.name, placeholderText=_("Office cluster"))
        self.host = QLineEdit(server.host, placeholderText="pve1.esempio.it")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(server.port)
        self.token = QLineEdit(server.token_id, placeholderText="utente@pve!spice")
        self.secret = QLineEdit(placeholderText="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" if is_new
                                else _("leave empty to keep the saved one"))
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Name:"), self.name)
        form.addRow(_("Host:"), self.host)
        form.addRow(_("Port:"), self.port)
        form.addRow(_("Token ID:"), self.token)
        form.addRow(_("Token secret:"), self.secret)
        layout.addLayout(form)

        self.trust_box = QFrame()
        self.trust_box.setFrameShape(QFrame.Shape.StyledPanel)
        trust_layout = QVBoxLayout(self.trust_box)
        warning = QLabel(texts.UNTRUSTED_CERT)
        warning.setWordWrap(True)
        trust_layout.addWidget(warning)
        self.fingerprint = QLabel()
        self.fingerprint.setWordWrap(True)
        self.fingerprint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = self.fingerprint.font()
        font.setFamily("monospace")
        self.fingerprint.setFont(font)
        trust_layout.addWidget(self.fingerprint)
        trust_layout.addWidget(note(texts.UNTRUSTED_CERT_HINT))
        trust = QPushButton(themed("security-medium"), _("Trust This Certificate"))
        trust.clicked.connect(self._trust)
        trust_layout.addWidget(trust, 0, Qt.AlignmentFlag.AlignLeft)
        self.trust_box.hide()
        layout.addWidget(self.trust_box)

        self.status = note("")
        layout.addWidget(self.status)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(_("Add") if is_new else _("Save"))
        self.buttons.accepted.connect(self._test)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for entry in (self.name, self.host, self.token, self.secret):
            entry.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        secret = self.secret.text().strip()
        valid = (is_valid_host(self.host.text().strip()) and is_valid_token_id(self.token.text().strip())
                 and (is_valid_secret(secret) if secret else not self.is_new))
        self.ok.setEnabled(valid and not self.working)

    def _trust(self):
        if self.untrusted:
            self.server = self.server.copy(pinned_sha256=self.untrusted)
            self.untrusted = None
            self.trust_box.hide()
            self._test()

    def _test(self):
        """Lists VMs with the entered settings; saves only when that works."""
        if self.working:
            return
        host = self.host.text().strip()
        candidate = self.server.copy(
            name=self.name.text().strip() or host, host=host, port=self.port.value(),
            token_id=self.token.text().strip(),
        )
        candidate = candidate_with_known_ca(self.app.store, candidate)
        typed_secret = self.secret.text().strip()
        self.working = True
        self._validate()
        self.status.setText(_("Connecting…"))

        def done(count, error):
            self.working = False
            self._validate()
            if isinstance(error, UntrustedCertificate):
                self.untrusted = error.sha256
                self.fingerprint.setText(f"SHA-256: {format_fingerprint(error.sha256)}")
                self.trust_box.show()
                self.status.setText("")
                self.adjustSize()  # make room for the wrapped texts
                return
            if error is not None:
                self.status.setText(error_text(error))
                return
            try:
                self.app.store.save_server(candidate, typed_secret or None)
            except Exception as save_error:
                self.status.setText(error_text(save_error))
                return
            self.accept()

        test_connection(self.app.store, candidate, typed_secret, done)
