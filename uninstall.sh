#!/bin/sh
# Removes what install.sh installed. Settings (~/.config/pxstation-linux) and the
# API token secrets in the keyring are kept unless you pass --purge.
set -eu

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
DESKTOP_ID=org.linuxspiceclient.LinuxSpiceClient.desktop

rm -rf "$DATA_HOME/pxstation-linux"
rm -f "$HOME/.local/bin/pxstation-linux" "$DATA_HOME/applications/$DESKTOP_ID"
find "$DATA_HOME/icons/hicolor" -name 'pxstation-linux.png' -delete 2>/dev/null || true
update-desktop-database -q "$DATA_HOME/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/pxstation-linux"
    python3 - <<'PY' || true
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
service = Secret.Service.get_sync(Secret.ServiceFlags.LOAD_COLLECTIONS, None)
for collection in service.get_collections() or []:
    for item in collection.get_items() or []:
        if item.get_schema_name() == "org.linuxspiceclient.LinuxSpiceClient.ProxmoxToken":
            item.delete_sync(None)
PY
    echo "Rimossi anche impostazioni e token API."
fi
echo "PxStation Linux è stato disinstallato."
