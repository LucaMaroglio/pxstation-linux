"""Interface selection and the toolkit-neutral parts of the controller.

    python3 -m unittest discover -s tests -t . -v
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linux_spice_client.core import i18n  # noqa: E402

i18n.load("it")  # the labels expected below are the Italian texts

from linux_spice_client.core import environment  # noqa: E402
from linux_spice_client.core.controller import Controller, MenuEntry  # noqa: E402
from linux_spice_client.core.proxmox import ProxmoxVM  # noqa: E402
from linux_spice_client.core.session import EndKind, State  # noqa: E402


class InterfaceChoiceTests(unittest.TestCase):
    def choose(self, env, qt=True, gtk=True):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(environment, "qt_available", return_value=qt), \
                mock.patch.object(environment, "gtk_available", return_value=gtk):
            return environment.choose_interface()

    def test_cinnamon_uses_gtk(self):
        self.assertEqual(self.choose({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}), ("gtk", None))

    def test_kde_uses_qt(self):
        self.assertEqual(self.choose({"XDG_CURRENT_DESKTOP": "KDE"}), ("qt", None))

    def test_kde_without_pyqt_falls_back(self):
        interface, warning = self.choose({"XDG_CURRENT_DESKTOP": "KDE"}, qt=False)
        self.assertEqual(interface, "gtk")
        self.assertIn("python3-pyqt6", warning)
        _interface, warning = self.choose({"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "5"}, qt=False)
        self.assertIn("python3-pyqt5", warning)

    def test_forced(self):
        self.assertEqual(self.choose({"XDG_CURRENT_DESKTOP": "KDE", "LSC_UI": "gtk"}), ("gtk", None))
        self.assertEqual(self.choose({"XDG_CURRENT_DESKTOP": "X-Cinnamon", "LSC_UI": "qt"}), ("qt", None))

    def test_desktop_detection(self):
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:KDE"}, clear=True):
            self.assertTrue(environment.is_kde())
        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "X-Cinnamon"}, clear=True):
            self.assertTrue(environment.is_cinnamon())
            self.assertFalse(environment.is_kde())


class QtBindingChoiceTests(unittest.TestCase):
    """Plasma integrates only the Qt version of its own session."""

    def choose(self, env, available=(6, 5)):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(environment, "qt_bindings", return_value=list(available)):
            return environment.choose_qt_binding()

    def test_plasma_5_uses_qt5(self):
        self.assertEqual(self.choose({"KDE_SESSION_VERSION": "5"}), (5, None))

    def test_plasma_6_uses_qt6(self):
        self.assertEqual(self.choose({"KDE_SESSION_VERSION": "6"}), (6, None))

    def test_unknown_session_prefers_qt6(self):
        self.assertEqual(self.choose({}), (6, None))
        self.assertEqual(self.choose({}, available=(5,)), (5, None))

    def test_missing_binding_falls_back_with_warning(self):
        major, warning = self.choose({"KDE_SESSION_VERSION": "5"}, available=(6,))
        self.assertEqual(major, 6)
        self.assertIn("python3-pyqt5", warning)
        major, warning = self.choose({"KDE_SESSION_VERSION": "6"}, available=(5,))
        self.assertEqual(major, 5)
        self.assertIn("python3-pyqt6", warning)

    def test_forced(self):
        self.assertEqual(self.choose({"KDE_SESSION_VERSION": "6", "LSC_QT": "5"}), (5, None))
        # forcing a binding that isn't installed is ignored
        self.assertEqual(self.choose({"KDE_SESSION_VERSION": "6", "LSC_QT": "5"}, available=(6,)), (6, None))

    def test_nothing_installed(self):
        self.assertEqual(self.choose({"KDE_SESSION_VERSION": "6"}, available=()), (None, None))


class DesktopActionTests(unittest.TestCase):
    def test_action_argument(self):
        from linux_spice_client.core import remote
        self.assertEqual(remote.take_action_argument(["lsc", "--action=vm-list"]), (["lsc"], "vm-list"))
        self.assertEqual(remote.take_action_argument(["lsc", "--action=rm-rf", "a.vv"]), (["lsc", "a.vv"], None))
        self.assertEqual(remote.take_action_argument(["lsc", "a.vv"]), (["lsc", "a.vv"], None))

    def test_desktop_file_actions_exist(self):
        from linux_spice_client.core import remote
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                            "org.linuxspiceclient.LinuxSpiceClient.desktop.in")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        listed = text.split("Actions=", 1)[1].split("\n", 1)[0].strip(";").split(";")
        for name in listed:
            self.assertIn(name, remote.ACTIONS)
            self.assertIn(f"[Desktop Action {name}]", text)
            self.assertIn(f"--action={name}", text)


class FakeSession:
    def __init__(self, state, end_kind=None, server=True, ref=True, busy=False):
        self.state = state
        self.end_kind = end_kind
        self.server = object() if server else None
        self.ref = mock.Mock(api_host="pve1") if ref else None
        self.can_control_power = server
        self.busy = busy
        self.end_message = "Connessione persa."
        self.is_active = state in (State.CONNECTING, State.CONNECTED, State.RECONNECTING)
        self.reconnect_now = self.cancel_reconnect = self.disconnect = lambda: None


class ControllerLogicTests(unittest.TestCase):
    def test_row_action(self):
        vm = lambda status: ProxmoxVM(100, "vm", "pve", status)  # noqa: E731
        self.assertEqual(Controller.row_action(vm("running"), None), ("Connetti", "connect"))
        self.assertEqual(Controller.row_action(vm("paused"), None), ("Riprendi e connetti", "connect"))
        self.assertEqual(Controller.row_action(vm("stopped"), None), ("Avvia e connetti", "connect"))
        self.assertEqual(Controller.row_action(vm("running"), FakeSession(State.CONNECTED)), ("Disconnetti", "disconnect"))
        self.assertEqual(Controller.row_action(vm("running"), FakeSession(State.RECONNECTING)),
                         ("Annulla riconnessione", "cancel"))

    def test_session_actions(self):
        self.assertEqual(Controller.session_actions(FakeSession(State.ENDED, EndKind.VM_NOT_RUNNING)),
                         [("start-reconnect", "Avvia e riconnetti")])
        self.assertEqual(Controller.session_actions(FakeSession(State.ENDED, EndKind.NO_API, server=False)),
                         [("setup-proxmox", "Configura accesso Proxmox…")])
        self.assertEqual(Controller.session_actions(FakeSession(State.ENDED, EndKind.DROPPED)),
                         [("reconnect", "Riconnetti")])
        self.assertEqual(Controller.session_actions(FakeSession(State.ENDED, EndKind.ONE_TIME_TICKET, server=False,
                                                                ref=False)), [])
        self.assertEqual(Controller.session_actions(FakeSession(State.CONNECTED)), [])

    def test_session_menu(self):
        controller = Controller.__new__(Controller)  # no store/keyring needed for the menu
        controller.ui = mock.Mock()
        controller.sessions = mock.Mock()
        labels = lambda entries: [e.label for e in entries if not e.separator]  # noqa: E731
        reconnecting = controller.session_entries(FakeSession(State.RECONNECTING))
        self.assertEqual(labels(reconnecting), ["Riprova ora", "Annulla riconnessione", "Alimentazione", "Disconnetti"])
        power = next(e for e in reconnecting if e.label == "Alimentazione")
        self.assertEqual(labels(power.children), ["Arresta", "Riavvia", "Metti in pausa", "Riprendi", "Reset…",
                                                  "Spegni forzatamente…"])
        ended_file = controller.session_entries(FakeSession(State.ENDED, EndKind.ONE_TIME_TICKET, server=False, ref=False))
        self.assertEqual(labels(ended_file), ["Connessione persa.", "Rimuovi dall’elenco"])
        self.assertTrue(isinstance(ended_file[0], MenuEntry) and not ended_file[0].sensitive)


class NotificationTests(unittest.TestCase):
    """A "session ended" notification has buttons and never expires, so it must disappear
    as soon as the session runs again or is gone."""

    def make(self):
        controller = Controller.__new__(Controller)
        controller.settings = mock.Mock(notifications=True)
        controller.notifier = mock.Mock()
        controller._ended_notes = set()
        controller.sessions = mock.Mock(sessions=[])
        controller.ui = mock.Mock()
        return controller

    def test_ended_notification_closed_when_session_reconnects(self):
        controller = self.make()
        session = FakeSession(State.ENDED, EndKind.VM_NOT_RUNNING)
        session.id = 7
        controller.sessions.sessions = [session]
        controller.notify(session, "VM: sessione terminata", "La VM è spenta.", ended=True)
        _key, _title, _body, actions, _cb = controller.notifier.show.call_args.args
        self.assertTrue(actions)
        controller.sessions_changed()
        controller.notifier.close.assert_not_called()  # still ended: keep it
        session.state = State.CONNECTING
        controller.sessions_changed()
        controller.notifier.close.assert_called_once_with(7)
        controller.notifier.close.reset_mock()
        controller.sessions_changed()
        controller.notifier.close.assert_not_called()

    def test_ended_notification_closed_when_session_removed(self):
        controller = self.make()
        session = FakeSession(State.ENDED, EndKind.DROPPED)
        session.id = 3
        controller.sessions.sessions = [session]
        controller.notify(session, "t", "b", ended=True)
        controller.sessions.sessions = []
        controller.sessions_changed()
        controller.notifier.close.assert_called_once_with(3)


class CoreHasNoToolkitTests(unittest.TestCase):
    def test_core_imports_no_gui_toolkit(self):
        core = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux_spice_client", "core")
        for name in os.listdir(core):
            if name.endswith(".py"):
                with open(os.path.join(core, name), encoding="utf-8") as handle:
                    source = handle.read()
                for toolkit in ("Gtk", "Gdk", "XApp", "PyQt6", "PySide"):
                    self.assertNotRegex(source, rf"(import|require_version\(\"){toolkit}\b", f"{name} uses {toolkit}")


if __name__ == "__main__":
    unittest.main()
