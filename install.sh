#!/bin/bash
# SCUF Envision Pro V2 Linux Driver - Installer
# Tested on Garuda Linux (Arch-based)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/scuf-envision"

echo "======================================"
echo "SCUF Envision Pro V2 - Linux Driver"
echo "======================================"
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh"
    exit 1
fi

# Step 1: Install python-evdev
echo "[1/6] Installing dependencies..."
if command -v pacman &>/dev/null; then
    pacman -S --noconfirm --needed python-evdev
elif command -v apt &>/dev/null; then
    apt install -y python3-evdev
elif command -v dnf &>/dev/null; then
    dnf install -y python3-evdev
else
    echo "Unknown package manager. Please install python-evdev manually."
    echo "  pip install evdev"
fi

# Step 2: Load uinput module
echo "[2/6] Loading uinput kernel module..."
modprobe uinput
if ! grep -q "^uinput$" /etc/modules-load.d/*.conf 2>/dev/null; then
    echo "uinput" > /etc/modules-load.d/uinput.conf
    echo "  Added uinput to /etc/modules-load.d/uinput.conf"
fi

# Step 3: Install udev rules
echo "[3/6] Installing udev rules..."
cp "$SCRIPT_DIR/99-scuf-envision.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger
echo "  Installed to /etc/udev/rules.d/99-scuf-envision.rules"

# Step 4: Install driver
echo "[4/6] Installing driver..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/scuf_envision" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/tools" "$INSTALL_DIR/"
echo "  Installed to $INSTALL_DIR"

# Step 5: Install and enable systemd service
echo "[5/6] Installing and enabling systemd service..."
cp "$SCRIPT_DIR/scuf-envision.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now scuf-envision.service
echo "  Service installed, enabled at boot, and started"

# Step 6: Install audio config
echo "[6/6] Installing audio config (headphone volume fix)..."
WP_CONF_DIR="/etc/wireplumber/wireplumber.conf.d"
OLD_DISABLE_RULE="/etc/udev/rules.d/98-scuf-no-audio.rules"
OLD_PW_GAIN_FILE="/etc/pipewire/pipewire.conf.d/50-scuf-gain.conf"
OLD_WP_GAIN_FILE="/etc/wireplumber/wireplumber.conf.d/50-scuf-gain.conf"
mkdir -p "$WP_CONF_DIR"
cp "$SCRIPT_DIR/50-scuf-audio.conf" "$WP_CONF_DIR/"
echo "  Installed WirePlumber config to $WP_CONF_DIR/50-scuf-audio.conf"
# Clean up old gain configs from previous installs
rm -f "$OLD_PW_GAIN_FILE" "$OLD_WP_GAIN_FILE"
if [ -f "$OLD_DISABLE_RULE" ]; then
    rm -f "$OLD_DISABLE_RULE"
    echo "  Removed old audio-disable workaround: $OLD_DISABLE_RULE"
fi
echo "  Note: Restart PipeWire/WirePlumber or reboot for audio changes to take effect"

echo ""
echo "======================================"
echo "Installation complete!"
echo "======================================"
echo ""

# Report service status
echo "Service status:"
if systemctl is-active --quiet scuf-envision.service; then
    echo "  [OK] scuf-envision.service is RUNNING"
else
    echo "  [!!] scuf-envision.service is NOT running"
    echo "       Check logs: journalctl -u scuf-envision.service -e"
fi
if systemctl is-enabled --quiet scuf-envision.service; then
    echo "  [OK] Enabled (will start automatically at boot)"
else
    echo "  [!!] NOT enabled at boot"
    echo "       Run: sudo systemctl enable scuf-envision.service"
fi
echo ""

echo "Useful commands:"
echo "  # Check service status:"
echo "  sudo systemctl status scuf-envision.service"
echo ""
echo "  # View service logs:"
echo "  journalctl -u scuf-envision.service -f"
echo ""
echo "  # Test with diagnostic tool:"
echo "  sudo python3 $INSTALL_DIR/tools/diag.py"
echo ""
echo "Steam users: set this environment variable to prevent double input:"
echo "  SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05,0x1b1c/0x3a08"
echo ""
