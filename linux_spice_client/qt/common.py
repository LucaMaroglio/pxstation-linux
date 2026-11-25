"""Small helpers shared by the Qt windows."""

from __future__ import annotations

import os

from .binding import QApplication, QColor, QEvent, QIcon, QLabel, QMenu, QObject, QPalette, QWidget

from .. import APP_SLUG, DATA_DIR
from ..core.controller import MenuEntry


def app_icon() -> QIcon:
    if QIcon.hasThemeIcon(APP_SLUG):
        return QIcon.fromTheme(APP_SLUG)
    icon = QIcon()
    hicolor = os.path.join(DATA_DIR, "icons", "hicolor")
    if os.path.isdir(hicolor):
        for size in sorted(os.listdir(hicolor)):
            path = os.path.join(hicolor, size, "apps", f"{APP_SLUG}.png")
            if os.path.exists(path):
                icon.addFile(path)
    return icon


def icon_file() -> str:
    """Icon name or file for notifications."""
    if QIcon.hasThemeIcon(APP_SLUG):
        return APP_SLUG
    return os.path.join(DATA_DIR, "icons", f"{APP_SLUG}.png")


def themed(name: str, fallback: str | None = None) -> QIcon:
    icon = QIcon.fromTheme(name)
    if icon.isNull() and fallback:
        icon = QIcon.fromTheme(fallback)
    return icon


def set_icon_or_text(button, name: str, text: str, fallback: str | None = None) -> None:
    """Icon from the theme (Breeze on KDE), or a short text where the theme has none."""
    icon = themed(name, fallback)
    if icon.isNull():
        button.setText(text)
    else:
        button.setIcon(icon)


def _apply_dim(label: QLabel) -> None:
    """Secondary text: the text colour faded towards the background, like KDE's own
    "inactive text". (Qt 5's KDE theme leaves PlaceholderText unset, which made these
    labels invisible on dark colour schemes.)"""
    palette = QApplication.palette(label)
    text = palette.color(QPalette.ColorRole.WindowText)
    back = palette.color(QPalette.ColorRole.Window)
    mixed = QColor(*(round(a * 0.65 + b * 0.35) for a, b in
                     ((text.red(), back.red()), (text.green(), back.green()), (text.blue(), back.blue()))))
    own = label.palette()
    own.setColor(QPalette.ColorRole.WindowText, mixed)
    label.setPalette(own)


class _Dimmer(QObject):
    """Recomputes dimmed colours when the user switches colour scheme."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ApplicationPaletteChange and isinstance(obj, QLabel):
            _apply_dim(obj)
        return False


_dimmer: _Dimmer | None = None


def dim(label: QLabel) -> QLabel:
    global _dimmer
    if _dimmer is None:
        _dimmer = _Dimmer()
    _apply_dim(label)
    label.installEventFilter(_dimmer)
    return label


def note(text: str, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    return dim(label)


def heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def build_menu(entries: list[MenuEntry], menu: QMenu | None = None) -> QMenu:
    menu = menu or QMenu()
    for entry in entries:
        if entry.separator:
            menu.addSeparator()
        elif entry.children:
            sub = menu.addMenu(entry.label)
            sub.setEnabled(entry.sensitive)
            build_menu(entry.children, sub)
        else:
            action = menu.addAction(entry.label)
            action.setEnabled(entry.sensitive)
            if entry.callback is not None:
                action.triggered.connect(lambda _checked=False, c=entry.callback: c())
    return menu
