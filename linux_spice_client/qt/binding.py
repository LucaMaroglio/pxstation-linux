"""The Qt binding for this session: PyQt5 on Plasma 5, PyQt6 on Plasma 6 (see
``core.environment.choose_qt_binding``). KDE integrates only the Qt version of the session,
so this decides whether windows get Breeze, the icon theme and KDE's file dialogs.

Use it like the binding itself: ``from .binding import QLabel, Qt, QAction``. Names are
looked up in QtCore, QtGui and QtWidgets (which also hides QAction's move from QtWidgets
in Qt 5 to QtGui in Qt 6). The code uses only API shared by PyQt 5.15 and PyQt6: scoped
enums (``Qt.AlignmentFlag.AlignLeft``) and ``exec()``.
"""

from __future__ import annotations

import importlib
import logging
import os

from ..core.environment import choose_qt_binding
from ..core.i18n import _

log = logging.getLogger(__name__)

QT_MAJOR, _warning = choose_qt_binding()
if QT_MAJOR is None:
    raise ImportError(_("PyQt5 or PyQt6 is not installed"))
if _warning:
    log.warning(_warning)

_PACKAGE = f"PyQt{QT_MAJOR}"
_MODULES = [importlib.import_module(f"{_PACKAGE}.{name}") for name in ("QtCore", "QtGui", "QtWidgets")]
QtCore, QtGui, QtWidgets = _MODULES
QT_VERSION = QtCore.QT_VERSION_STR


def __getattr__(name: str):
    for module in _MODULES:
        if hasattr(module, name):
            value = getattr(module, name)
            globals()[name] = value
            return value
    raise AttributeError(f"{_PACKAGE} has no {name}")


def translations_path() -> str:
    info = QtCore.QLibraryInfo
    if QT_MAJOR == 6:
        return info.path(info.LibraryPath.TranslationsPath)
    return info.location(info.TranslationsPath)


def plugins_path() -> str:
    info = QtCore.QLibraryInfo
    if QT_MAJOR == 6:
        return info.path(info.LibraryPath.PluginsPath)
    return info.location(info.PluginsPath)


def has_kde_integration() -> bool:
    """True when Plasma's platform theme plugin exists for this Qt version: it gives Breeze,
    the icon theme and KDE's own file dialogs to every Qt application."""
    directory = os.path.join(plugins_path(), "platformthemes")
    try:
        return any(name.startswith("KDEPlasmaPlatformTheme") for name in os.listdir(directory))
    except OSError:
        return False


def has_svg_icons() -> bool:
    """Qt's SVG icon engine (package libqt5svg5 / libqt6svg6): Breeze icons are SVG."""
    return os.path.exists(os.path.join(plugins_path(), "iconengines", "libqsvgicon.so"))


def before_application() -> None:
    """Settings that must precede QApplication: sharp rendering on HiDPI screens with Qt 5
    (Qt 6 always does it)."""
    if QT_MAJOR == 5:
        Qt = QtCore.Qt
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
