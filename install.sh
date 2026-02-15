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
echo "[1/5] Installing dependencies..."
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
echo "[2/5] Loading uinput kernel module..."
modprobe uinput
if ! grep -q "^uinput$" /etc/modules-load.d/*.conf 2>/dev/null; then
    echo "uinput" > /etc/modules-load.d/uinput.conf
    echo "  Added uinput to /etc/modules-load.d/uinput.conf"
fi

# Step 3: Install udev rules
echo "[3/5] Installing udev rules..."
cp "$SCRIPT_DIR/99-scuf-envision.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger
echo "  Installed to /etc/udev/rules.d/99-scuf-envision.rules"

# Step 4: Install driver
echo "[4/5] Installing driver..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/scuf_envision" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/tools" "$INSTALL_DIR/"
echo "  Installed to $INSTALL_DIR"

# Step 5: Install systemd service
echo "[5/5] Installing systemd service..."
cp "$SCRIPT_DIR/scuf-envision.service" /etc/systemd/system/
systemctl daemon-reload
echo "  Service installed (not started yet)"

echo ""
echo "======================================"
echo "Installation complete!"
echo "======================================"
echo ""
echo "Quick start:"
echo "  # Test with diagnostic tool first:"
echo "  sudo python3 $INSTALL_DIR/tools/diag.py"
echo ""
echo "  # Run the driver manually:"
echo "  sudo python3 -m scuf_envision"
echo "  (run from $INSTALL_DIR)"
echo ""
echo "  # Or enable as a service:"
echo "  sudo systemctl enable --now scuf-envision.service"
echo ""
echo "  # Check service status:"
echo "  sudo systemctl status scuf-envision.service"
echo ""
echo "Steam users: set this environment variable to prevent double input:"
echo "  SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05,0x1b1c/0x3a08"
echo ""
