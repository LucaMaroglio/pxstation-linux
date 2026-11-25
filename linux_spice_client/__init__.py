"""PxStation Linux: Proxmox VE virtual machines on the Linux desktop (Cinnamon with
GTK, KDE Plasma with Qt), shown through remote-viewer (virt-viewer).

Layout:
    core/  everything shared: Proxmox API, sessions and reconnection, settings, keyring,
           notifications, menus content (no toolkit code)
    gtk/   GTK 3 interface (Cinnamon)
    qt/    Qt 6 interface (KDE Plasma)
"""

import os

APP_ID = "org.linuxspiceclient.LinuxSpiceClient"
APP_NAME = "PxStation Linux"
APP_SLUG = "pxstation-linux"
VERSION = "0.3.1"
COPYRIGHT = "2026 - Zenity.it"
UPSTREAM_URL = "https://github.com/pawelwiecaszek/macos-spice-client"  # this program is a fork of it

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
