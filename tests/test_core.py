"""Unit tests: .vv files, Proxmox models/client (against the fake API), session logic.

    python3 -m unittest discover -s tests -v
"""

import hashlib
import os
import ssl
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linux_spice_client.core import proxmox, vvfile  # noqa: E402
from linux_spice_client.core.session import Outcome, ReconnectPolicy, ViewerLog  # noqa: E402

PROXMOX_VV = (
    "﻿[virt-viewer]\r\n"
    "type=spice\r\n"
    "host=pvespiceproxy:6566b2a1:100:pve1::4b1c8f\r\n"
    "proxy=http://192.168.1.10:3128\r\n"
    "tls-port=61000\r\n"
    "password=secretticket\r\n"
    "ca=-----BEGIN CERTIFICATE-----\\nMIIB\\n-----END CERTIFICATE-----\\n\r\n"
    "title=VM 100 - debian\r\n"
    "delete-this-file=1\r\n"
    "[ovirt]\r\nhost=ignored\r\n"
)


class VVFileTests(unittest.TestCase):
    def test_parse_proxmox_file(self):
        values = vvfile.parse(PROXMOX_VV)
        self.assertEqual(values["tls-port"], "61000")
        self.assertEqual(values["ca"], "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
        self.assertEqual(vvfile.proxmox_ref(values), vvfile.VMRef("192.168.1.10", "pve1", 100))
        self.assertEqual(vvfile.display_title(values), "VM 100 - debian")

    def test_roundtrip(self):
        values = vvfile.parse(PROXMOX_VV)
        self.assertEqual(vvfile.parse(vvfile.serialize(values)), values)

    def test_rejects_other_types_and_missing_section(self):
        with self.assertRaises(vvfile.VVFileError):
            vvfile.parse("[virt-viewer]\ntype=vnc\nhost=x\n")
        with self.assertRaises(vvfile.VVFileError):
            vvfile.parse("[other]\nhost=x\n")
        with self.assertRaises(vvfile.VVFileError):
            vvfile.parse("[virt-viewer]\ntype=spice\n")

    def test_non_proxmox_has_no_ref(self):
        self.assertIsNone(vvfile.proxmox_ref({"host": "10.0.0.5", "port": "5900"}))
        self.assertIsNone(vvfile.proxmox_ref({"host": "pvespiceproxy:a:x:pve1", "proxy": "http://h:3128"}))

    def test_ipv6_proxy(self):
        ref = vvfile.proxmox_ref({"host": "pvespiceproxy:t:101:node2::x", "proxy": "http://[fd00::5]:3128"})
        self.assertEqual(ref, vvfile.VMRef("fd00::5", "node2", 101))

    def test_from_proxmox_json_unescapes_ca_once(self):
        values = vvfile.from_proxmox_json({
            "ca": "-----BEGIN CERTIFICATE-----\\nAAA\\n-----END CERTIFICATE-----\\n",
            "tls-port": 61000, "delete-this-file": 1, "secure-attention": "Ctrl+Alt+Ins",
            "Bad Key": "x", "nested": {"a": 1},
        })
        self.assertEqual(values["ca"], "-----BEGIN CERTIFICATE-----\nAAA\n-----END CERTIFICATE-----\n")
        self.assertEqual(values["tls-port"], "61000")
        self.assertNotIn("Bad Key", values)
        self.assertNotIn("nested", values)
        text = vvfile.serialize(values)
        self.assertIn("ca=-----BEGIN CERTIFICATE-----\\nAAA\\n", text)


class ModelTests(unittest.TestCase):
    def test_token_id(self):
        self.assertTrue(proxmox.is_valid_token_id("root@pam!spice"))
        for bad in ("root@pam", "rootpam!x", "root@pam!", "a@b!c d", "a@b!c\r\nX: y", "a@b!c!d"):
            self.assertFalse(proxmox.is_valid_token_id(bad), bad)

    def test_secret(self):
        self.assertTrue(proxmox.is_valid_secret("11111111-2222-3333-4444-555555555555"))
        self.assertFalse(proxmox.is_valid_secret("not-a-uuid"))
        self.assertFalse(proxmox.is_valid_secret("{11111111-2222-3333-4444-555555555555}"))

    def test_host(self):
        for good in ("pve1", "pve1.example.com", "192.168.1.10", "[fd00::1]", "fd00::1"):
            self.assertTrue(proxmox.is_valid_host(good), good)
        for bad in ("", "pve 1", "pve1/x", "pve1:8006", "-pve", "http://pve1"):
            self.assertFalse(proxmox.is_valid_host(bad), bad)

    def test_power_actions(self):
        P = proxmox.PowerAction
        self.assertEqual(proxmox.power_actions_for("running"), [P.SHUTDOWN, P.REBOOT, P.SUSPEND, P.RESET, P.STOP])
        self.assertEqual(proxmox.power_actions_for("paused"), [P.RESUME, P.STOP])
        self.assertEqual(proxmox.power_actions_for("stopped"), [P.START])
        self.assertTrue(P.STOP.is_destructive and P.RESET.is_destructive and not P.SHUTDOWN.is_destructive)

    def test_qmp_timeout(self):
        self.assertTrue(proxmox.is_qmp_timeout("VM 100 qmp command 'query-spice' failed - got timeout"))
        self.assertFalse(proxmox.is_qmp_timeout("VM 100 not running"))

    def test_rejects_bad_node(self):
        client = proxmox.ProxmoxClient(proxmox.ProxmoxServer("x", "127.0.0.1", "a@b!c", port=1),
                                       "11111111-2222-3333-4444-555555555555")
        with self.assertRaises(proxmox.InvalidConfiguration):
            client.status("../../access", 100)


class ViewerLogTests(unittest.TestCase):
    PREFIX = "(remote-viewer:1): virt-viewer-DEBUG: 00:25:44.564: "

    def run_lines(self, lines, exit_ok=True):
        log = ViewerLog()
        for line in lines:
            log.feed(self.PREFIX + line)
        return log.outcome(exit_ok)

    def test_server_dropped(self):
        # Captured from remote-viewer 11 when QEMU went away (two timings seen).
        self.assertEqual(self.run_lines(["main channel: opened", "main channel: closed", "notebook show status 0x1",
                                         "Guest QEMU 8.2.2 display has disconnected, shutting down"]), Outcome.DROPPED)
        self.assertEqual(self.run_lines(["main channel: opened", "main channel: closed",
                                         "Destroying spice display 0x1", "Destroy SPICE channel SpiceMainChannel 0",
                                         "zap main channel", "notebook show status 0x1"]), Outcome.DROPPED)

    def test_io_error_after_open(self):
        self.assertEqual(self.run_lines(["main channel: opened",
                                         "main channel: failed to connect Connection reset by peer"]), Outcome.DROPPED)

    def test_user_closed(self):
        # Captured: window closed by the user, quit confirmed.
        self.assertEqual(self.run_lines(["main channel: opened", "Window closed",
                                         "Destroy SPICE channel SpiceMainChannel 0", "zap main channel",
                                         "main channel: closed", "notebook show status 0x1"]), Outcome.USER_CLOSED)

    def test_cancelled_close_then_drop(self):
        self.assertEqual(self.run_lines(["main channel: opened", "Window closed", "main channel: closed",
                                         "zap main channel"]), Outcome.DROPPED)

    def test_connect_failed(self):
        self.assertEqual(self.run_lines(["main channel: failed to connect Connessione rifiutata"]),
                         Outcome.CONNECT_FAILED)

    def test_auth_failed(self):
        self.assertEqual(self.run_lines(["main channel: auth failure (wrong username/password?)"]),
                         Outcome.AUTH_FAILED)

    def test_crash(self):
        self.assertEqual(self.run_lines([], exit_ok=False), Outcome.CRASHED)
        self.assertEqual(self.run_lines(["main channel: opened"], exit_ok=False), Outcome.DROPPED)


class PolicyTests(unittest.TestCase):
    def test_delays(self):
        policy = ReconnectPolicy()
        self.assertEqual([policy.delay(n) for n in range(1, 9)], [1, 2, 4, 8, 15, 30, 30, 30])
        self.assertIsNone(policy.delay(9))
        self.assertIsNone(policy.delay(0))


class FakeServerTests(unittest.TestCase):
    """The real client against the fake Proxmox API (TLS, pinning, CA, endpoints)."""

    @classmethod
    def setUpClass(cls):
        from tests import fake_proxmox
        cls.fake = fake_proxmox
        ready = threading.Event()
        holder = {}

        def on_ready(server, cert):
            holder["server"], holder["cert"] = server, cert
            ready.set()

        cls.thread = threading.Thread(target=fake_proxmox.serve, args=(18106, 15990, on_ready), daemon=True)
        cls.thread.start()
        if not ready.wait(20):
            raise RuntimeError("fake server did not start")
        cls.server = holder["server"]
        with open(holder["cert"]) as handle:
            cls.cert_pem = handle.read()
        der = ssl.PEM_cert_to_DER_cert(cls.cert_pem)
        cls.fingerprint = hashlib.sha256(der).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(10)

    def client(self, **changes):
        server = proxmox.ProxmoxServer("fake", "127.0.0.1", self.fake.TOKEN_ID, port=18106)
        return proxmox.ProxmoxClient(server.copy(**changes), self.fake.SECRET)

    def test_untrusted_certificate_reports_fingerprint(self):
        with self.assertRaises(proxmox.UntrustedCertificate) as caught:
            self.client().virtual_machines()
        self.assertEqual(caught.exception.sha256, self.fingerprint)

    def test_wrong_pin_is_refused(self):
        with self.assertRaises(proxmox.UntrustedCertificate):
            self.client(pinned_sha256="00" * 32).virtual_machines()

    def test_cluster_ca_is_trusted(self):
        vms = self.client(cluster_ca_pem=self.cert_pem).virtual_machines()
        self.assertEqual([vm.vmid for vm in vms], [100, 102, 101])

    def test_pinned_flow(self):
        client = self.client(pinned_sha256=self.fingerprint)
        vms = client.virtual_machines()
        self.assertEqual([vm.name for vm in vms], ["debian-test", "paused-test", "windows-test"])
        detailed = {vm.vmid: vm.status for vm in client.with_detailed_states(vms)}
        self.assertEqual(detailed, {100: "running", 101: "stopped", 102: "paused"})
        payload = client.spice_proxy("pve-test", 100)
        self.assertEqual(payload["proxy-requested"], "127.0.0.1")
        with self.assertRaises(proxmox.HTTPError):
            client.spice_proxy("pve-test", 101)

    def test_bad_secret(self):
        server = proxmox.ProxmoxServer("fake", "127.0.0.1", self.fake.TOKEN_ID, port=18106,
                                       pinned_sha256=self.fingerprint)
        client = proxmox.ProxmoxClient(server, "99999999-2222-3333-4444-555555555555")
        with self.assertRaises(proxmox.Unauthorized):
            client.virtual_machines()

    def test_unreachable(self):
        with self.assertRaises(proxmox.TransportError):
            self.client(port=1).virtual_machines()


if __name__ == "__main__":
    unittest.main()
