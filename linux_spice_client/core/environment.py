"""Which desktop we run on, and which interface to use there.

* KDE Plasma → Qt interface (``linux_spice_client.qt``)
* everything else (Cinnamon first) → GTK interface (``linux_spice_client.gtk``)

``LSC_UI=gtk`` or ``LSC_UI=qt`` forces one.

The Qt interface runs on the Qt version of the Plasma session, because KDE integrates only
that one (style, icons, file dialogs): PyQt5 on Plasma 5, PyQt6 on Plasma 6.
``LSC_QT=5`` or ``LSC_QT=6`` forces one.
"""

from __future__ import annotations

import importlib.util
import os
from .i18n import _

GTK = "gtk"
QT = "qt"


def desktops() -> list[str]:
    value = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    return [part.strip().lower() for part in value.replace(";", ":").split(":") if part.strip()]


def is_kde() -> bool:
    return "kde" in desktops() or os.environ.get("KDE_FULL_SESSION") == "true"


def is_cinnamon() -> bool:
    return any(name in ("x-cinnamon", "cinnamon") for name in desktops())


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def plasma_version() -> int | None:
    """Major version of the running Plasma session (set by startplasma), if any."""
    value = os.environ.get("KDE_SESSION_VERSION", "").strip()
    return int(value) if value.isdigit() else None


def qt_bindings() -> list[int]:
    """Installed PyQt major versions, newest first."""
    return [major for major in (6, 5) if importlib.util.find_spec(f"PyQt{major}") is not None]


def qt_available() -> bool:
    return bool(qt_bindings())


def choose_qt_binding() -> tuple[int | None, str | None]:
    """PyQt major version for this session and, when it isn't the right one, why."""
    available = qt_bindings()
    forced = os.environ.get("LSC_QT", "").strip()
    if forced in ("5", "6") and int(forced) in available:
        return int(forced), None
    if not available:
        return None, None
    plasma = plasma_version()
    preferred = 5 if plasma == 5 else 6
    if preferred in available:
        return preferred, None
    fallback = available[0]
    if plasma == 5:
        return fallback, (_("PyQt5 is not installed: on Plasma 5 the Qt 6 interface lacks KDE’s style, icons and dialogs (sudo apt install python3-pyqt5)."))
    if plasma:
        return fallback, (_("PyQt6 is not installed: using Qt 5, less integrated with Plasma {plasma} (sudo apt install python3-pyqt6).").format(plasma=plasma))
    return fallback, None


def gtk_available() -> bool:
    """GTK 3 typelib present (checked without loading GTK into this process)."""
    try:
        import gi
        try:
            gi.require_version("GIRepository", "2.0")
        except ValueError:
            pass
        from gi.repository import GIRepository
        return "3.0" in GIRepository.Repository.get_default().enumerate_versions("Gtk")
    except (ImportError, AttributeError):
        return False


def choose_interface() -> tuple[str, str | None]:
    """Returns the interface and, when it isn't the preferred one, why."""
    forced = (os.environ.get("LSC_UI") or "").strip().lower()
    if forced in (GTK, QT):
        return forced, None
    if is_kde():
        if qt_available():
            return QT, None
        package = "python3-pyqt5" if plasma_version() == 5 else "python3-pyqt6"
        return GTK, _("PyQt is not installed: using the GTK interface (sudo apt install {package}).").format(package=package)
    if gtk_available():
        return GTK, None
    if qt_available():
        return QT, _("GTK 3 is not available: using the Qt interface.")
    return GTK, None
