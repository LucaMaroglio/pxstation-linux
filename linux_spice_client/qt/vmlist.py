""""Macchine virtuali" window (Qt): VMs of every configured Proxmox server, with power
actions and one-click connect. Same behaviour as the GTK window, KDE look."""

from __future__ import annotations

from .binding import (QAction, QFrame, QGroupBox, QHBoxLayout, QKeySequence, QLabel, QMainWindow, QMenu,
                      QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, Qt, QTimer, QToolBar,
                      QToolButton, QVBoxLayout, QWidget)

from ..core import texts
from ..core.controller import Controller, VMListLoader
from ..core.proxmox import PowerAction, ProxmoxServer, ProxmoxVM, power_actions_for
from ..core.session import State
from ..core.util import error_text
from ..core.vvfile import VMRef
from .common import dim, heading, note, set_icon_or_text, themed
from ..core.i18n import _


class VMRow(QFrame):
    def __init__(self, window: "VMListWindow", server: ProxmoxServer, vm: ProxmoxVM):
        super().__init__()
        self.window = window
        self.server = server
        self.vm = vm
        self._button_action = "connect"
        self._menu_for = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 6, 6)
        self.dot = QLabel("●")
        layout.addWidget(self.dot)

        column = QVBoxLayout()
        column.setSpacing(1)
        self.name_label = QLabel()
        self.caption = dim(QLabel())
        self.session_label = dim(QLabel())
        column.addWidget(self.name_label)
        column.addWidget(self.caption)
        column.addWidget(self.session_label)
        layout.addLayout(column, 1)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setMaximumWidth(48)
        self.busy.setTextVisible(False)
        layout.addWidget(self.busy)

        self.button = QPushButton()
        self.button.clicked.connect(self._on_button)
        layout.addWidget(self.button)

        self.power = QToolButton()
        set_icon_or_text(self.power, "system-shutdown", "⏻")
        self.power.setToolTip(_("Power"))
        self.power.setAutoRaise(True)
        self.power.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self.power)
        self.update_vm(vm)

    @property
    def ref(self) -> VMRef:
        return VMRef(self.server.host, self.vm.node, self.vm.vmid)

    def update_vm(self, vm: ProxmoxVM) -> None:
        self.vm = vm
        busy = vm.key in self.window.busy
        session = self.window.app.sessions.session_for(self.ref)

        self.dot.setStyleSheet(f"color: {texts.status_color(vm.status)};")
        self.dot.setToolTip(vm.status_label)
        self.name_label.setText(vm.name)
        self.caption.setText(f"{vm.vmid} · {vm.node} · {vm.status_label}")
        if session is not None:
            self.session_label.setText(_("Session: {status}").format(status=session.status_text()))
            self.session_label.setToolTip(session.status_text())
        self.session_label.setVisible(session is not None)
        self.busy.setVisible(busy or (session is not None and session.busy))

        label, self._button_action = Controller.row_action(vm, session)
        self.button.setText(label)
        self.button.setToolTip(_("Opens {name} in a new window").format(name=vm.name) if self._button_action == "connect" else "")
        self.button.setEnabled(not busy)
        self.power.setEnabled(not busy)
        if self._menu_for != vm.status:
            self._menu_for = vm.status
            self._menu = self._build_menu()
            self.power.setMenu(self._menu)

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        for action in power_actions_for(self.vm.status):
            item = menu.addAction(themed(action.icon.replace("-symbolic", "")), action.title)
            item.triggered.connect(lambda _c=False, a=action: self.window.run_power(a, self.vm, self.server))
        return menu

    def contextMenuEvent(self, event):
        if self.power.isEnabled():
            self._build_menu().exec(event.globalPos())

    def _on_button(self):
        session = self.window.app.sessions.session_for(self.ref)
        if self._button_action == "disconnect" and session:
            session.disconnect()
        elif self._button_action == "cancel" and session:
            session.cancel_reconnect()
        else:
            self.window.connect_vm(self.vm, self.server)


class ServerSection(QGroupBox):
    def __init__(self, window: "VMListWindow", server: ProxmoxServer):
        super().__init__(server.name)
        self.window = window
        self.server = server
        self.rows: dict[str, VMRow] = {}
        layout = QVBoxLayout(self)
        self.message = note("")
        layout.addWidget(self.message)
        self.container = QWidget()
        layout.addWidget(self.container)
        self.set_loading()

    def set_loading(self):
        self.message.setText(_("Loading…"))
        self.message.show()

    def set_error(self, text: str):
        self.message.setText(f"⚠ {text}")
        self.message.show()

    def set_vms(self, vms: list[ProxmoxVM]):
        keys = [vm.key for vm in vms]
        if keys != list(self.rows):
            # Replace the whole list (simplest way to drop rows and separators together).
            old_container = self.container
            self.container = QWidget()
            box = QVBoxLayout(self.container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            self.rows = {}
            for index, vm in enumerate(vms):
                if index:
                    line = QFrame()
                    line.setFrameShape(QFrame.Shape.HLine)
                    line.setFrameShadow(QFrame.Shadow.Sunken)
                    box.addWidget(line)
                row = VMRow(self.window, self.server, vm)
                self.rows[vm.key] = row
                box.addWidget(row)
            self.layout().replaceWidget(old_container, self.container)
            old_container.deleteLater()
        else:
            for vm in vms:
                self.rows[vm.key].update_vm(vm)
        if vms:
            self.message.hide()
        else:
            self.message.setText(texts.EMPTY_TOKEN_HINT)
            self.message.show()

    def refresh_rows(self):
        for row in self.rows.values():
            row.update_vm(row.vm)


class VMListWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.busy: set[str] = set()
        self.sections: dict[str, ServerSection] = {}
        self.setWindowTitle(_("Virtual Machines"))
        self.resize(640, 540)

        toolbar = QToolBar(_("Main toolbar"))
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.refresh_action = QAction(themed("view-refresh"), _("Refresh"), self)
        self.refresh_action.setShortcuts([QKeySequence("Ctrl+R"), QKeySequence(QKeySequence.StandardKey.Refresh)])
        self.refresh_action.triggered.connect(self.reload)
        toolbar.addAction(self.refresh_action)
        open_action = QAction(themed("document-open"), _("Open File…"), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(lambda: app.controller.choose_and_open())
        toolbar.addAction(open_action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        menu = QMenu(self)
        prefs = menu.addAction(themed("configure", "preferences-system"), _("Configure PxStation Linux…"))
        prefs.setShortcut(QKeySequence.StandardKey.Preferences)
        prefs.triggered.connect(lambda: app.show_preferences())
        menu.addSeparator()
        menu.addAction(themed("help-about"), _("About"), app.show_about)
        quit_action = menu.addAction(themed("application-exit"), _("Quit"))
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(lambda: app.controller.request_quit())
        self.addActions([prefs, quit_action])
        menu_button = QToolButton()
        set_icon_or_text(menu_button, "application-menu", _("Menu"), "open-menu")
        menu_button.setToolTip(_("Menu"))
        menu_button.setMenu(menu)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(menu_button)
        self.addToolBar(toolbar)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # Empty state
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(themed("network-server").pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(icon)
        title = heading(texts.NO_SERVERS_TITLE)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(title)
        text = note(texts.NO_SERVERS)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(text)
        settings_button = QPushButton(themed("configure"), _("Configure Server…"))
        settings_button.clicked.connect(lambda: app.show_preferences(page="proxmox"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(settings_button)
        row.addStretch(1)
        empty_layout.addLayout(row)
        empty_layout.addStretch(1)
        self.stack.addWidget(empty)

        # List
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.banner = QFrame()
        self.banner.setStyleSheet("QFrame { background: rgba(218, 68, 83, 0.15); border: 1px solid "
                                  "rgba(218, 68, 83, 0.6); border-radius: 4px; }"
                                  "QLabel, QToolButton { background: transparent; border: none; }")
        banner_layout = QHBoxLayout(self.banner)
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        banner_layout.addWidget(self.banner_label, 1)
        close = QToolButton()
        close.setIcon(themed("dialog-close", "window-close"))
        close.clicked.connect(self.banner.hide)
        banner_layout.addWidget(close)
        self.banner.hide()
        page_layout.addWidget(self.banner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.sections_box = QVBoxLayout(holder)
        self.sections_box.addStretch(1)
        scroll.setWidget(holder)
        page_layout.addWidget(scroll)
        self.stack.addWidget(page)

        self.loader = VMListLoader(app.store, self._on_result,
                                   lambda loading: self.refresh_action.setEnabled(not loading))
        self.timer = QTimer(self)
        self.timer.setInterval(texts.REFRESH_SECONDS * 1000)
        self.timer.timeout.connect(self.reload)
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self._on_tick)

        app.store.connect_changed(self._on_servers_changed)
        self.destroyed.connect(lambda: app.store.disconnect_changed(self._on_servers_changed))
        self._rebuild_sections()

    # Visibility

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
        self.timer.start()
        self.tick.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()
        self.tick.stop()

    def closeEvent(self, event):
        super().closeEvent(event)
        self.app.window_closed()

    # Servers

    def _on_servers_changed(self):
        self._rebuild_sections()
        if self.isVisible():
            self.reload()

    def _rebuild_sections(self):
        servers = self.app.store.servers
        if [s.id for s in servers] != list(self.sections) or any(self.sections[s.id].server != s for s in servers):
            for section in self.sections.values():
                section.setParent(None)
                section.deleteLater()
            self.sections = {}
            for index, server in enumerate(servers):
                section = ServerSection(self, server)
                self.sections[server.id] = section
                self.sections_box.insertWidget(index, section)
        self.stack.setCurrentIndex(1 if servers else 0)

    def _on_tick(self):
        if any(s.state == State.RECONNECTING for s in self.app.sessions.sessions):
            self.sessions_changed()

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
            self.banner_label.setText(text)
            self.banner.show()
        else:
            self.banner.hide()

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
