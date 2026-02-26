#!/usr/bin/env bash
# install.sh — OpenVPN GUI Client installer
set -euo pipefail

APP_NAME="vpn-client"
INSTALL_DIR="/opt/${APP_NAME}"
DESKTOP_FILE="/usr/share/applications/${APP_NAME}.desktop"
LAUNCHER="/usr/local/bin/${APP_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || error "Run as root:  sudo bash install.sh"
}

check_dep() {
    local cmd="$1" pkg="$2"
    if ! command -v "$cmd" &>/dev/null; then
        warn "'$cmd' not found. Install package: $pkg"
        return 1
    fi
}

detect_pkg_manager() {
    if command -v dnf  &>/dev/null; then echo "dnf"
    elif command -v apt &>/dev/null; then echo "apt"
    elif command -v pacman &>/dev/null; then echo "pacman"
    else echo "unknown"
    fi
}

install_deps() {
    local pm
    pm="$(detect_pkg_manager)"
    info "Package manager: $pm"

    case "$pm" in
        dnf)
            dnf install -y openvpn python3 python3-gobject gtk4 libadwaita polkit
            ;;
        apt)
            apt-get install -y openvpn python3 python3-gi python3-gi-cairo \
                gir1.2-gtk-4.0 gir1.2-adw-1 policykit-1
            ;;
        pacman)
            pacman -Sy --noconfirm openvpn python python-gobject gtk4 libadwaita polkit
            ;;
        *)
            warn "Unknown package manager — install dependencies manually:"
            echo "  openvpn, python3, PyGObject (python3-gobject / python3-gi),"
            echo "  GTK4, libadwaita, polkit/pkexec"
            ;;
    esac
}

verify_deps() {
    local ok=true
    info "Checking runtime dependencies..."
    check_dep python3   "python3"          || ok=false
    check_dep openvpn   "openvpn"          || ok=false
    check_dep pkexec    "polkit"           || ok=false

    # Check PyGObject (GTK4 + Adwaita)
    if ! python3 -c "
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Adw
" 2>/dev/null; then
        warn "PyGObject with GTK4/Adwaita not found (python3-gobject / python3-gi + gir1.2-adw-1)"
        ok=false
    fi

    $ok || error "Missing dependencies — run:  sudo bash install.sh --install-deps"
}

install_app() {
    info "Installing to ${INSTALL_DIR} ..."
    mkdir -p "${INSTALL_DIR}"
    install -m 755 "${SCRIPT_DIR}/vpn_client.py" "${INSTALL_DIR}/vpn_client.py"

    # Copy .ovpn configs if present
    local count=0
    for f in "${SCRIPT_DIR}"/*.ovpn; do
        [[ -f "$f" ]] || continue
        install -m 600 "$f" "${INSTALL_DIR}/"
        (( count++ )) || true
    done
    [[ $count -gt 0 ]] && info "Copied $count .ovpn config(s)." \
                        || warn "No .ovpn files found. Add them to ${INSTALL_DIR}/ later."

    # Launcher wrapper
    cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
exec python3 "${INSTALL_DIR}/vpn_client.py" "\$@"
EOF
    chmod 755 "${LAUNCHER}"
    info "Launcher: ${LAUNCHER}"

    # Desktop entry
    cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Name=VPN Client
Comment=OpenVPN GUI client (GTK4/Adwaita)
Exec=${LAUNCHER}
Icon=network-vpn
Terminal=false
Type=Application
Categories=Network;Security;
Keywords=vpn;openvpn;
EOF
    info "Desktop entry: ${DESKTOP_FILE}"

    # Refresh desktop database if available
    command -v update-desktop-database &>/dev/null && \
        update-desktop-database /usr/share/applications/ || true

    info "Installation complete. Launch with:  ${APP_NAME}"
}

uninstall_app() {
    info "Uninstalling ${APP_NAME} ..."
    rm -rf  "${INSTALL_DIR}"
    rm -f   "${LAUNCHER}" "${DESKTOP_FILE}"
    info "Uninstall complete."
}

print_help() {
    echo "Usage: sudo bash install.sh [OPTION]"
    echo ""
    echo "Options:"
    echo "  (none)            Install the application (after verifying deps)"
    echo "  --install-deps    Install system dependencies then install the app"
    echo "  --uninstall       Remove the application"
    echo "  --check           Check dependencies only"
    echo "  -h, --help        Show this help message"
}

# ── Main ──────────────────────────────────────────────────────────────────────

case "${1:-}" in
    --install-deps)
        require_root
        install_deps
        verify_deps
        install_app
        ;;
    --uninstall)
        require_root
        uninstall_app
        ;;
    --check)
        verify_deps
        info "All dependencies satisfied."
        ;;
    -h|--help)
        print_help
        ;;
    "")
        require_root
        verify_deps
        install_app
        ;;
    *)
        error "Unknown option: $1  (use --help)"
        ;;
esac
