"""virt-viewer connection files (.vv): parsing, writing and Proxmox references.

Same format and rules as the macOS client (VVFile module): INI-style, a
``[virt-viewer]`` section, GKeyFile escaping (``\\n``, ``\\\\``, ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from .i18n import _

SECTION = "virt-viewer"
MAX_FILE_BYTES = 1024 * 1024

_KEY_RE = re.compile(r"^[a-z0-9-]+$")


class VVFileError(ValueError):
    pass


def _unescape(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "r": "\r", "t": "\t", "s": " ", "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")


def parse(text: str) -> dict[str, str]:
    """Returns the keys of the ``[virt-viewer]`` section. Other sections are ignored."""
    if text.startswith("\ufeff"):
        text = text[1:]
    section = None
    values: dict[str, str] = {}
    found = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            found = found or section == SECTION
            continue
        if section != SECTION or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _unescape(value.strip())
    if not found:
        raise VVFileError(_("The file has no [virt-viewer] section."))
    kind = values.get("type", "spice").lower()
    if kind != "spice":
        raise VVFileError(_("Unsupported connection type: {kind}.").format(kind=kind))
    if not values.get("host"):
        raise VVFileError(_("The connection file doesn’t specify the host."))
    return values


def read(path: str) -> dict[str, str]:
    with open(path, "rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise VVFileError(_("The connection file is too large."))
    try:
        return parse(data.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise VVFileError(_("The connection file is not UTF-8 text.")) from error


def serialize(values: dict[str, str]) -> str:
    lines = [f"[{SECTION}]"]
    for key in sorted(values):
        lines.append(f"{key}={_escape(values[key])}")
    return "\n".join(lines) + "\n"


def from_proxmox_json(obj: dict) -> dict[str, str]:
    """Turns the JSON object of ``POST …/spiceproxy`` into .vv values.

    Proxmox already escapes the CA for the .vv file (``$cacert =~ s/\\n/\\\\n/g``),
    so the API value holds literal ``\\n`` sequences: undo that first.
    """
    values: dict[str, str] = {}
    for key, value in obj.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            continue
        if isinstance(value, bool):
            text = "1" if value else "0"
        elif isinstance(value, (str, int, float)):
            text = str(value)
        else:
            continue
        if key == "ca":
            text = text.replace("\\n", "\n")
        values[key] = text
    return values


@dataclass(frozen=True)
class VMRef:
    """The Proxmox VM a connection points at."""

    api_host: str
    node: str
    vmid: int


def proxmox_ref(values: dict[str, str]) -> VMRef | None:
    """Proxmox hosts look like ``pvespiceproxy:<ticket>:<vmid>:<node>::<…>`` and the proxy
    is the node itself (``http://<node>:3128``)."""
    proxy = values.get("proxy")
    if not proxy:
        return None
    fields = values.get("host", "").split(":")
    if len(fields) < 4 or fields[0] != "pvespiceproxy" or not fields[3]:
        return None
    try:
        vmid = int(fields[2])
    except ValueError:
        return None
    if vmid <= 0:
        return None
    host = urlsplit(proxy).hostname
    if not host:
        return None
    return VMRef(api_host=host, node=fields[3], vmid=vmid)


def display_title(values: dict[str, str]) -> str:
    title = values.get("title")
    if title:
        return title
    ref = proxmox_ref(values)
    if ref:
        return f"VM {ref.vmid}"
    return values.get("host", "SPICE")
