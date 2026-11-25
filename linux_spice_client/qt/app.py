"""Qt interface (KDE Plasma): QApplication, windows and a QSystemTrayIcon (on Plasma it is
a StatusNotifierItem, so it works on Wayland too). All logic lives in
``core.controller``; this module only draws.

Single instance and the ``.vv`` hand-over use a Gio.Application with the same D-Bus name
as the GTK interface: Qt runs the GLib main loop (QEventDispatcherGlib), so GLib/Gio
callbacks of the shared core run unchanged inside ``QApplication.exec()``.

Qt version: PyQt5 on Plasma 5, PyQt6 on Plasma 6 (``binding``), so that Plasma's platform
theme gives Breeze, the icon theme and KDE's file dialogs. Without it (wrong Qt version
installed) the icon theme is read from kdeglobals and files are chosen through the portal.

Wayland: the windows carry the desktop file's id (app_id → icon and task manager entry),
and the activation token of a launch that reaches the running instance (a ``.vv`` from the
browser, a desktop-file action, a second start) is handed to Qt, so KWin brings the window
to the front instead of just flagging it.
"""

from __future__ import annotations

import logging
import os

from gi.repository import Gio, GLib

from .. import APP_ID, APP_NAME, APP_SLUG, COPYRIGHT, VERSION
from ..core import environment, i18n, portal, remote
from ..core.controller import Controller
from . import binding
from .binding import (QApplication, QEventLoop, QFileDialog, QIcon, QLocale, QMenu, QMessageBox,
                      QSystemTrayIcon, QTimer, QTranslator)
from .common import app_icon, build_menu, icon_file
from ..core.i18n import _

log = logging.getLogger(__name__)

VV_FILTERS = [(_("virt-viewer connection files"), ["*.vv"]), (_("All files"), ["*"])]


class _GApplication(Gio.Application):
    """Gio.Application that reports the platform data (activation token) of every request
    coming from another process before the request itself runs."""

    def __init__(self, on_platform_data):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._on_platform_data = on_platform_data

    def do_add_platform_data(self, builder):
        """Sender side (a second start handing over files or a request): pass on this
        launch's activation token. GtkApplication does this by itself, Gio.Application not."""
        Gio.Application.do_add_platform_data(self, builder)
        for key, value in remote.platform_data().items():
            builder.add_value(GLib.Variant("{sv}", (key, value)))

    def do_before_emit(self, platform_data):
        Gio.Application.do_before_emit(self, platform_data)
        self._on_platform_data(platform_data.unpack() if platform_data else {})


class Application:
    def __init__(self, qapp: QApplication, gapp: _GApplication, action: str | None = None):
        self.qapp = qapp
        self.icon_name = APP_SLUG
        self.controller: Controller | None = None
        self._vm_list = None
        self._preferences = None
        self._welcome = None
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu = None
        self._tray_signature = None
        self._dialogs = []  # non-modal message boxes kept alive while shown
        self._pending_action = action
        self.kde_integration = binding.has_kde_integration()

        self.gapp = gapp
        self.gapp.connect("activate", lambda _a: self.controller and self.controller.activate())
        self.gapp.connect("open", self._on_open)
        for name, callback in (
            ("open-file", lambda *_: self.controller.choose_and_open()),
            ("vm-list", lambda *_: self.show_vm_list()),
            ("preferences", lambda *_: self.show_preferences()),
            ("about", lambda *_: self.show_about()),
            ("quit", lambda *_: self.controller.request_quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.gapp.add_action(action)

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

    def run(self, argv: list[str]) -> int:
        self.controller = Controller(self)
        self.update_tray()
        files = [arg for arg in argv[1:] if not arg.startswith("-")]
        if files:
            self.controller.open_paths([Gio.File.new_for_commandline_arg(f).get_path() for f in files])
        elif self._pending_action:
            self.gapp.activate_action(self._pending_action, None)
        else:
            self.controller.activate()
        self._check_keepalive()
        code = self.qapp.exec()
        self.controller.shutdown()
        return code

    def _on_open(self, _gapp, files, _n_files, _hint):
        if self.controller:
            self.controller.open_paths([f.get_path() for f in files if f.get_path()])

    def window_closed(self):
        QTimer.singleShot(0, self._check_keepalive)

    def _check_keepalive(self):
        """Quit when nothing is left: no tray icon, no session, no visible window."""
        if self._tray is not None or self.sessions.sessions:
            return
        if any(w.isVisible() for w in self.qapp.topLevelWidgets()):
            return
        self.qapp.quit()

    # MARK: UserInterface

    def icon(self) -> str:
        return icon_file()

    def refresh(self):
        if self._vm_list is not None:
            self._vm_list.sessions_changed()
        self._refresh_tray_menu()
        self.window_closed()

    def _present(self, window):
        window.show()
        window.raise_()
        window.activateWindow()

    def show_vm_list(self):
        from .vmlist import VMListWindow
        if self._vm_list is None:
            self._vm_list = VMListWindow(self)
        self._present(self._vm_list)
        self.close_welcome()  # the list replaces it (also when opened from the tray or a desktop action)

    def show_welcome(self):
        from .welcome import WelcomeWindow
        if self._welcome is None:
            self._welcome = WelcomeWindow(self)
        self._present(self._welcome)

    def close_welcome(self):
        if self._welcome is not None:
            self._welcome.close()

    def show_preferences(self, page: str | None = None, add_host: str | None = None):
        from .preferences import PreferencesWindow
        if self._preferences is None:
            self._preferences = PreferencesWindow(self)
        if page or add_host:
            self._preferences.show_page(page or "proxmox")
        self._present(self._preferences)
        if add_host and self.store.server_for_host(add_host) is None:
            self._preferences.servers_page.edit(None, host=add_host)

    def choose_file(self) -> str | None:
        title = _("Open Connection File")
        parent = self.qapp.activeWindow()
        if not self.kde_integration and environment.is_kde():
            # Qt can't show KDE's dialog by itself here: ask the portal (KDE draws it).
            result = {}
            loop = QEventLoop()

            def done(path):
                result["path"] = path
                loop.quit()

            if portal.open_file(_portal_parent(parent), title, VV_FILTERS, done):
                if "path" not in result:
                    loop.exec()
                return result.get("path")
        filters = ";;".join(f"{name} ({' '.join(globs)})" for name, globs in VV_FILTERS)
        path, _filter = QFileDialog.getOpenFileName(parent, title, "", filters)
        return path or None

    def message(self, title: str, text: str, error: bool = True, parent=None):
        box = QMessageBox(QMessageBox.Icon.Critical if error else QMessageBox.Icon.Information,
                          APP_NAME, title, QMessageBox.StandardButton.Close, parent or self.qapp.activeWindow())
        box.setInformativeText(text)
        box.setWindowIcon(app_icon())
        box.finished.connect(lambda _r, b=box: (self._dialogs.remove(b), self.window_closed()))
        self._dialogs.append(box)
        box.open()

    def confirm(self, title: str, text: str, accept: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, title, QMessageBox.StandardButton.NoButton,
                          self.qapp.activeWindow())
        box.setInformativeText(text)
        ok = box.addButton(accept, QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(_("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    def ask_quit(self) -> str | None:
        box = QMessageBox(QMessageBox.Icon.Question, APP_NAME, _("Close the open sessions too?"),
                          QMessageBox.StandardButton.NoButton, self.qapp.activeWindow())
        box.setInformativeText(_("If you leave them open, the remote-viewer windows stay active but without the power menu or automatic reconnection."))
        close = box.addButton(_("Close Sessions"), QMessageBox.ButtonRole.DestructiveRole)
        leave = box.addButton(_("Leave Open"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "close" if clicked is close else "leave" if clicked is leave else None

    def quit_app(self):
        self.qapp.quit()

    def show_about(self):
        QMessageBox.about(self.qapp.activeWindow(), _("About {name}").format(name=APP_NAME),
                          f"<h3>{APP_NAME}</h3><p>{_('Version {version}').format(version=VERSION)}</p>"
                          f"<p>{COPYRIGHT}</p>")

    # MARK: Tray icon

    def update_tray(self):
        want = bool(self.settings.show_tray_icon) and QSystemTrayIcon.isSystemTrayAvailable()
        if want and self._tray is None:
            self._tray = QSystemTrayIcon(app_icon())
            self._tray.setToolTip(APP_NAME)
            # One menu for the icon's whole life, refilled in place: on Plasma the menu is
            # exported over D-Bus (StatusNotifierItem) and a replaced QMenu isn't picked up.
            self._tray_menu = QMenu()
            self._tray.setContextMenu(self._tray_menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray_signature = None
            self._refresh_tray_menu()
            self._tray.show()
        elif not want and self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
            self.window_closed()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.controller.activate()

    def _refresh_tray_menu(self):
        if self._tray is None:
            return
        signature = self.controller.tray_signature()
        if signature == self._tray_signature:
            return
        self._tray_signature = signature
        self._tray_menu.clear()
        build_menu(self.controller.tray_entries(), self._tray_menu)
        self._tray.setToolTip(self.controller.tray_tooltip())


def _use_activation_token(platform_data: dict) -> None:
    """Hands a launch's activation token to Qt: on Wayland, Qt uses XDG_ACTIVATION_TOKEN for
    the next window activation, and KWin only raises windows activated with a valid token."""
    token = platform_data.get("activation-token")
    log.debug("request from another process, activation token: %s", "yes" if token else "no")
    if token and environment.is_wayland():
        os.environ["XDG_ACTIVATION_TOKEN"] = token
    startup_id = platform_data.get("desktop-startup-id")
    if startup_id and not environment.is_wayland():
        os.environ["DESKTOP_STARTUP_ID"] = startup_id


def _portal_parent(window) -> str:
    """Window identifier for the portal, so its dialog is modal to our window (X11 only:
    on Wayland that needs an exported surface handle, which PyQt doesn't offer)."""
    if window is not None and QApplication.platformName() == "xcb":
        return f"x11:{int(window.winId()):x}"
    return ""


def _icon_search_paths(current: list[str]) -> list[str]:
    """The XDG icon directories (~/.local/share/icons, ~/.icons, $XDG_DATA_DIRS/icons)."""
    candidates = [os.path.join(GLib.get_user_data_dir(), "icons"), os.path.expanduser("~/.icons")]
    candidates += [os.path.join(d, "icons") for d in GLib.get_system_data_dirs()]
    paths = list(current)
    for path in candidates:
        if os.path.isdir(path) and path not in paths:
            paths.append(path)
    return paths


def _kde_icon_theme() -> str | None:
    """Icon theme chosen in Plasma's settings (kdeglobals [Icons] Theme)."""
    paths = [os.path.join(GLib.get_user_config_dir(), "kdeglobals")]
    paths += [os.path.join(d, "kdeglobals") for d in GLib.get_system_config_dirs()]
    for path in paths:
        keyfile = GLib.KeyFile()
        try:
            keyfile.load_from_file(path, GLib.KeyFileFlags.NONE)
            return keyfile.get_string("Icons", "Theme")
        except GLib.Error:
            continue
    return None


def run(argv: list[str], action: str | None = None) -> int:
    # Single instance first, before Qt connects to the display: a second start only hands
    # its files (or the request to show the window) to the running instance, with its token.
    gapp = _GApplication(_use_activation_token)
    try:
        gapp.register(None)
    except GLib.Error as error:
        log.warning("D-Bus registration failed: %s", error.message)
    if gapp.get_is_remote():
        return gapp.run(argv)

    binding.before_application()
    qapp = QApplication(argv)
    qapp.setApplicationName(APP_SLUG)
    qapp.setApplicationDisplayName(APP_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setDesktopFileName(APP_ID)  # Wayland app_id → icon and task manager entry
    qapp.setQuitOnLastWindowClosed(False)
    integrated = binding.has_kde_integration()
    log.info("Qt %s (PyQt%s), %s, KDE integration: %s", binding.QT_VERSION, binding.QT_MAJOR,
             QApplication.platformName(), "yes" if integrated else "no")
    if not integrated and environment.is_kde():
        # Without Plasma's platform theme Qt doesn't know the icon theme, nor (with some
        # themes) where icon themes live: give it both.
        QIcon.setThemeSearchPaths(_icon_search_paths(QIcon.themeSearchPaths()))
        QIcon.setThemeName(_kde_icon_theme() or "breeze")
        QIcon.setFallbackThemeName("breeze")
    if not binding.has_svg_icons():
        log.warning("Manca il motore di icone SVG di Qt %s: i pulsanti mostreranno testo invece delle icone "
                    "(sudo apt install libqt%ssvg%s).", binding.QT_MAJOR, binding.QT_MAJOR, binding.QT_MAJOR)
    qapp.setWindowIcon(app_icon())
    # Qt's own strings (OK, Annulla, Chiudi…) in the user's language, when installed.
    translator = QTranslator(qapp)
    if translator.load(QLocale(i18n.current_language()), "qtbase", "_", binding.translations_path()):
        qapp.installTranslator(translator)
    return Application(qapp, gapp, action).run(argv)
