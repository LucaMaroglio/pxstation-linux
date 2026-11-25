"""Welcome window (Qt): shown when there are no Proxmox servers and no connection file."""

from __future__ import annotations

from .binding import QHBoxLayout, QLabel, QPushButton, Qt, QVBoxLayout, QWidget

from .. import APP_NAME
from ..core import texts
from .common import app_icon, heading, note, themed
from ..core.i18n import _


class WelcomeWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle(_("Welcome"))
        self.setAcceptDrops(True)
        self.setFixedWidth(500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(96, 96))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        title = heading(APP_NAME)
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        text = note(texts.WELCOME)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        open_button = QPushButton(themed("document-open"), _("Open Connection File…"))
        open_button.setDefault(True)
        open_button.clicked.connect(lambda: app.controller.choose_and_open())
        buttons.addWidget(open_button)
        vms = QPushButton(themed("computer"), _("Virtual Machines…"))
        vms.clicked.connect(self._vm_list)
        buttons.addWidget(vms)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        hint = note(_("or drop a .vv file here"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _vm_list(self):
        self.app.show_vm_list()
        self.close()

    def closeEvent(self, event):
        super().closeEvent(event)
        self.app.window_closed()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() and url.toLocalFile().lower().endswith(".vv") for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".vv"):
                self.app.controller.open_path(url.toLocalFile())
        event.acceptProposedAction()
