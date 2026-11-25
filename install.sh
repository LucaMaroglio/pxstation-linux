#!/bin/sh
# Installs PxStation Linux for the current user (no root needed):
#   ~/.local/share/pxstation-linux   program files
#   ~/.local/bin/pxstation-linux     launcher
#   ~/.local/share/applications         menu entry (.vv files can be opened with it)
#   ~/.local/share/icons/hicolor        icon
set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
PREFIX="$DATA_HOME/pxstation-linux"
BIN="$HOME/.local/bin"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor"
DESKTOP_ID=org.linuxspiceclient.LinuxSpiceClient.desktop

# Dependencies (all in the Linux Mint / Ubuntu / KDE neon archives). The shared core needs
# remote-viewer, PyGObject, libsecret and libnotify; then the interface for this desktop:
# Qt on KDE Plasma, in the Qt version of the session (PyQt5 on Plasma 5, PyQt6 on Plasma 6,
# the only one Plasma integrates), GTK 3 + XApp elsewhere (Cinnamon).
case ":${XDG_CURRENT_DESKTOP:-}:" in
    *:KDE:*|*:kde:*) INTERFACE=qt ;;
    *) INTERFACE=gtk ;;
esac
[ -n "${LSC_UI:-}" ] && INTERFACE=$LSC_UI

missing=""
command -v remote-viewer >/dev/null 2>&1 || missing="$missing virt-viewer"
python3 - <<'PY' 2>/dev/null || missing="$missing python3-gi gir1.2-secret-1 gir1.2-notify-0.7"
import gi
gi.require_version("Secret", "1"); gi.require_version("Notify", "0.7")
from gi.repository import Secret, Notify
PY
if [ "$INTERFACE" = qt ]; then
    case "${LSC_QT:-${KDE_SESSION_VERSION:-6}}" in 5) QT=5 ;; *) QT=6 ;; esac
    if python3 -c "import PyQt$QT.QtWidgets" 2>/dev/null; then
        # Breeze and most icon themes are SVG: without Qt's SVG icon engine buttons lose
        # their icons (Plasma itself always has it, but for its own Qt version only).
        python3 - "$QT" <<'PY' 2>/dev/null || missing="$missing libqt${QT}svg${QT}"
import importlib, os, sys
qt = sys.argv[1]
core = importlib.import_module(f"PyQt{qt}.QtCore")
info = core.QLibraryInfo
plugins = info.path(info.LibraryPath.PluginsPath) if qt == "6" else info.location(info.PluginsPath)
sys.exit(0 if os.path.exists(os.path.join(plugins, "iconengines", "libqsvgicon.so")) else 1)
PY
    else
        missing="$missing python3-pyqt$QT"
    fi
else
    python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null \
        || missing="$missing gir1.2-gtk-3.0"
    python3 -c 'import gi; gi.require_version("XApp", "1.0"); from gi.repository import XApp' 2>/dev/null \
        || missing="$missing gir1.2-xapp-1.0"
fi
if [ -n "$missing" ]; then
    echo "Mancano alcuni pacchetti. Installali con:"
    echo "  sudo apt install$missing"
    exit 1
fi
if [ "$INTERFACE" = qt ]; then
    echo "Interfaccia per questo desktop: qt (Qt $QT)"
else
    echo "Interfaccia per questo desktop: $INTERFACE"
fi

echo "Installazione in $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$BIN" "$APPS" "$ICONS"
cp -r "$SRC/linux_spice_client" "$SRC/bin" "$PREFIX/"
mkdir -p "$PREFIX/data"
cp -r "$SRC/data/icons" "$SRC/data/locale" "$PREFIX/data/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} +
chmod 755 "$PREFIX/bin/pxstation-linux"
ln -sf "$PREFIX/bin/pxstation-linux" "$BIN/pxstation-linux"

for dir in "$SRC"/data/icons/hicolor/*/apps; do
    size=$(basename "$(dirname "$dir")")
    mkdir -p "$ICONS/$size/apps"
    cp "$dir/pxstation-linux.png" "$ICONS/$size/apps/"
done
gtk-update-icon-cache -q -t "$ICONS" 2>/dev/null || true

sed "s|@EXEC@|$PREFIX/bin/pxstation-linux|" "$SRC/data/$DESKTOP_ID.in" > "$APPS/$DESKTOP_ID"
chmod 644 "$APPS/$DESKTOP_ID"
update-desktop-database -q "$APPS" 2>/dev/null || true

echo "Fatto. Trovi “PxStation Linux” nel menu delle applicazioni."
echo "Per aprire i file .vv con questo programma: Preferenze › Generale › File di connessione."
