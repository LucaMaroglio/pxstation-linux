"""User-facing texts and constants shared by both interfaces, so GTK and Qt say exactly
the same thing."""

from .. import APP_NAME
from . import i18n
from .i18n import _

REFRESH_SECONDS = 10

WELCOME = (_("Open a virt-viewer connection file (.vv), for example the one your browser downloads when you click “SPICE” in Proxmox VE, or manage the virtual machines of your Proxmox servers."))

NO_SERVERS_TITLE = _("No Proxmox Servers")
NO_SERVERS = (_("Add a Proxmox server with an API token to start, stop and connect to virtual machines from here."))

EMPTY_TOKEN_HINT = (
    _("No virtual machines are visible to this API token. Give the token (not only its user) VM.Audit, VM.PowerMgmt and VM.Console, e.g. the PVEVMUser role on /vms, or turn off its privilege separation.")
)

SERVERS_FOOTNOTE = (
    _("Used for Start, Shut Down, Reboot, the Virtual Machines window and reconnecting. Create an API token in Proxmox (Datacenter › Permissions › API Tokens) with VM.Audit, VM.PowerMgmt and VM.Console on your VMs. The secret is stored in the keyring.")
)

UNTRUSTED_CERT = (_("The server’s certificate isn’t trusted by the system or by a Proxmox CA this program has seen."))
UNTRUSTED_CERT_HINT = (_("Compare it with Proxmox › node › System › Certificates (pve-ssl.pem) before trusting it."))

ABOUT = _("Proxmox VE virtual machines on the Linux desktop, shown with remote-viewer.")
CREDITS = _("Based on macos-spice-client by Paweł Więcaszek (MIT license)")

# (attribute, title, note) for the General preferences, in order, grouped by heading.
GENERAL_SETTINGS = [
    (_("Connection"), [
        ("reconnect_automatically", _("Reconnect automatically when the connection drops"),
         _("Retries for about two minutes, waiting for the network to come back. Proxmox sessions get a fresh ticket through the API (needs the server set up in the Proxmox tab); a downloaded file’s ticket works only once.")),
    ]),
    (_("Display"), [
        ("open_full_screen", _("Open sessions in full screen"),
         _("The guest resolution follows the screen when spice-vdagent is installed in the VM.")),
    ]),
    (_("Desktop"), [
        ("show_tray_icon", _("Show the icon in the notification area"),
         _("The icon gives access to open sessions, the power menu and reconnecting. With the icon on, the program keeps running even without open windows.")),
        ("notifications", _("Show notifications for sessions"), None),
    ]),
]

VV_FOOTNOTE = (_("When this program opens the files your browser downloads after clicking “SPICE” in Proxmox, those sessions get the power menu and automatic reconnection too. The VM window is still remote-viewer’s."))


LANGUAGE_HEADING = _("Language")


def language_choices() -> list[tuple[str, str]]:
    """(code, label) for the language menu: "" is the system default."""
    system = i18n.language_name(i18n.system_language())
    return [("", _("System default ({language})").format(language=system))] + [
        (code, i18n.language_name(code)) for code in i18n.supported_languages()]


def language_note(selected: str) -> str:
    if selected != i18n.chosen_at_start():
        return _("Restart {name} to use the new language.").format(name=APP_NAME)
    return _("The system default follows the system language settings; English is used if none of those languages is available.")


def status_color(status: str) -> str:
    return {"running": "#2ec27e", "paused": "#f5a623", "suspended": "#f5a623"}.get(status, "#9a9996")


def vv_handler_text(is_default: bool, current: str | None) -> str:
    if is_default:
        return _(".vv files open with this program.")
    return _(".vv files now open with: {program}.").format(program=current or _("no program"))
