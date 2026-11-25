#!/usr/bin/env python3
"""A tiny fake Proxmox VE API for development and tests.

Serves the endpoints PxStation Linux uses over HTTPS with a self-signed certificate,
and backs every "running" VM with a real local QEMU process that has a SPICE display, so
remote-viewer can actually connect.

    python3 tests/fake_proxmox.py --port 18006

Token:  test@pve!spice  /  secret 11111111-2222-3333-4444-555555555555
Extra:  GET /test/drop/<vmid> restarts that VM's QEMU (simulates a dropped connection
        while the VM keeps running); GET /test/state shows the current states.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

TOKEN_ID = "test@pve!spice"
SECRET = "11111111-2222-3333-4444-555555555555"
NODE = "pve-test"


class VM:
    def __init__(self, vmid, name, status, spice_port):
        self.vmid = vmid
        self.name = name
        self.status = status  # running | stopped
        self.paused = False
        self.spice_port = spice_port
        self.process: subprocess.Popen | None = None

    def start_qemu(self):
        self.stop_qemu()
        self.process = subprocess.Popen(
            ["qemu-system-x86_64", "-m", "64", "-display", "none", "-vga", "qxl", "-name", self.name,
             "-spice", f"port={self.spice_port},addr=127.0.0.1,disable-ticketing=on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop_qemu(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class State:
    def __init__(self, base_port):
        self.lock = threading.Lock()
        self.vms = {
            100: VM(100, "debian-test", "running", base_port),
            101: VM(101, "windows-test", "stopped", base_port + 1),
            102: VM(102, "paused-test", "running", base_port + 2),
        }
        self.vms[102].paused = True
        for vm in self.vms.values():
            if vm.status == "running":
                vm.start_qemu()

    def shutdown(self):
        for vm in self.vms.values():
            vm.stop_qemu()


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("fake-proxmox: " + (fmt % args) + "\n")

        def _send(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            if self.headers.get("Authorization") != f"PVEAPIToken={TOKEN_ID}={SECRET}":
                self._send(401, {"data": None, "message": "authentication failure"})
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path.startswith("/test/"):
                return self._test(url.path)
            if not self._authorized():
                return
            if url.path == "/api2/json/cluster/resources":
                with state.lock:
                    data = [{"type": "qemu", "vmid": vm.vmid, "name": vm.name, "node": NODE,
                             "status": vm.status, "template": 0, "id": f"qemu/{vm.vmid}"}
                            for vm in state.vms.values()]
                data.append({"type": "qemu", "vmid": 9000, "name": "template", "node": NODE,
                             "status": "stopped", "template": 1})
                return self._send(200, {"data": data})
            match = re.fullmatch(rf"/api2/json/nodes/{NODE}/qemu/(\d+)/status/current", url.path)
            if match:
                vm = state.vms.get(int(match.group(1)))
                if vm is None:
                    return self._send(500, {"data": None, "message": "VM not found"})
                with state.lock:
                    data = {"status": vm.status, "vmid": vm.vmid, "name": vm.name}
                    if vm.status == "running":
                        data["qmpstatus"] = "paused" if vm.paused else "running"
                return self._send(200, {"data": data})
            self._send(501, {"data": None, "message": "not implemented"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(length).decode()) if length else {}
            if not self._authorized():
                return
            match = re.fullmatch(rf"/api2/json/nodes/{NODE}/qemu/(\d+)/(status/(\w+)|spiceproxy)", urlsplit(self.path).path)
            vm = state.vms.get(int(match.group(1))) if match else None
            if vm is None:
                return self._send(501, {"data": None, "message": "not implemented"})
            with state.lock:
                if match.group(2) == "spiceproxy":
                    if vm.status != "running":
                        return self._send(500, {"data": None, "message": f"VM {vm.vmid} not running"})
                    return self._send(200, {"data": {
                        "type": "spice", "host": "127.0.0.1", "port": vm.spice_port,
                        "title": f"VM {vm.vmid} - {vm.name}", "delete-this-file": 1,
                        "toggle-fullscreen": "Shift+F11", "release-cursor": "Ctrl+Alt+R",
                        "secure-attention": "Ctrl+Alt+Ins", "proxy-requested": form.get("proxy", [""])[0],
                    }})
                action = match.group(3)
                if action == "start" and vm.status == "stopped":
                    vm.status, vm.paused = "running", False
                    vm.start_qemu()
                elif action in ("stop", "shutdown"):
                    vm.status, vm.paused = "stopped", False
                    vm.stop_qemu()
                elif action == "suspend":
                    vm.paused = True
                elif action == "resume":
                    vm.paused = False
                elif action in ("reboot", "reset"):
                    pass
                else:
                    return self._send(400, {"data": None, "message": f"bad action {action}"})
                return self._send(200, {"data": f"UPID:{NODE}:task:{action}"})

        def _test(self, path):
            if path == "/test/state":
                with state.lock:
                    return self._send(200, {vm.vmid: {"status": vm.status, "paused": vm.paused}
                                            for vm in state.vms.values()})
            match = re.fullmatch(r"/test/drop/(\d+)", path)
            vm = state.vms.get(int(match.group(1))) if match else None
            if vm is None or vm.status != "running":
                return self._send(404, {"error": "no running vm"})
            with state.lock:
                vm.start_qemu()
            return self._send(200, {"dropped": vm.vmid})

    return Handler


def make_certificate(directory: str) -> tuple[str, str]:
    cert, key = os.path.join(directory, "cert.pem"), os.path.join(directory, "key.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout", key, "-out", cert], check=True, capture_output=True)
    return cert, key


def serve(port: int, spice_base: int, ready=None, directory: str | None = None):
    directory = directory or tempfile.mkdtemp(prefix="fake-proxmox-")
    cert, key = make_certificate(directory)
    state = State(spice_base)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    if ready:
        ready(server, cert)
    try:
        server.serve_forever()
    finally:
        state.shutdown()
        shutil.rmtree(directory, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=18006)
    parser.add_argument("--spice-base", type=int, default=15900)
    args = parser.parse_args()

    def ready(server, cert):
        print(f"Fake Proxmox on https://127.0.0.1:{args.port} (token {TOKEN_ID}, secret {SECRET})", flush=True)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        serve(args.port, args.spice_base, ready)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
