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

# Step 1: Install dependencies
echo "[1/8] Installing dependencies..."
if command -v pacman &>/dev/null; then
    pacman -S --noconfirm --needed python-evdev libnotify python-pyqt6 python-pillow
elif command -v apt &>/dev/null; then
    apt install -y python3-evdev libnotify-bin python3-pyqt6 python3-pil
    # Fallback to pip if distro package is missing
    pip install --quiet PyQt6 2>/dev/null || true
elif command -v dnf &>/dev/null; then
    dnf install -y python3-evdev libnotify python3-pillow
    pip install --quiet PyQt6 2>/dev/null || true
else
    echo "Unknown package manager. Please install python-evdev and libnotify manually."
    echo "  pip install evdev PyQt6 pillow"
fi

# Ensure 'input' group exists (safety net for minimal installs; usually pre-exists)
getent group input &>/dev/null || groupadd --system input

# Step 2: Load uinput module
echo "[2/8] Loading uinput kernel module..."
modprobe uinput
if ! grep -q "^uinput$" /etc/modules-load.d/*.conf 2>/dev/null; then
    echo "uinput" > /etc/modules-load.d/uinput.conf
    echo "  Added uinput to /etc/modules-load.d/uinput.conf"
fi

# Step 3: Install udev rules
echo "[3/8] Installing udev rules..."
cp "$SCRIPT_DIR/99-scuf-envision.rules" /etc/udev/rules.d/
udevadm control --reload-rules
udevadm trigger
echo "  Installed to /etc/udev/rules.d/99-scuf-envision.rules"

# Step 4: Install driver and tools
echo "[4/8] Installing driver..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/scuf_envision" "$INSTALL_DIR/"
cp -r "$SCRIPT_DIR/tools" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/uninstall.sh" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/tools/scuf-audio-toggle"
chmod +x "$INSTALL_DIR/tools/scuf-ctl"
chmod +x "$INSTALL_DIR/tools/scuf-profile"
chmod +x "$INSTALL_DIR/tools/tray.py"
ln -sf "$INSTALL_DIR/tools/scuf-audio-toggle" /usr/local/bin/scuf-audio-toggle
ln -sf "$INSTALL_DIR/tools/scuf-ctl"          /usr/local/bin/scuf-ctl
ln -sf "$INSTALL_DIR/tools/scuf-profile"      /usr/local/bin/scuf-profile
ln -sf "$INSTALL_DIR/tools/tray.py"           /usr/local/bin/scuf-tray
echo "  Installed to $INSTALL_DIR"
echo "  Installed scuf-audio-toggle, scuf-ctl, scuf-profile, scuf-tray to /usr/local/bin/"

# Install XDG autostart entry (starts tray with the desktop session)
AUTOSTART_DIR="/etc/xdg/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/tools/scuf-tray.desktop" "$AUTOSTART_DIR/"
echo "  Installed autostart entry to $AUTOSTART_DIR/scuf-tray.desktop"

# Step 5: Install default config
echo "[5/8] Installing default config..."
CONF_DIR="/etc/scuf-envision"
CONF_FILE="$CONF_DIR/config.ini"
mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_FILE" ]; then
    cp "$SCRIPT_DIR/config.ini.default" "$CONF_FILE"
    echo "  Installed default config to $CONF_FILE"
else
    echo "  Config already exists at $CONF_FILE (preserved)"
fi

# Step 6: Install and enable systemd service
echo "[6/8] Installing and enabling systemd service..."
cp "$SCRIPT_DIR/scuf-envision.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable scuf-envision.service
systemctl restart scuf-envision.service
echo "  Service installed, enabled at boot, and started"

# Step 7: Install audio config
echo "[7/8] Installing audio config (headphone volume fix)..."
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

# Step 8: Summary
echo "[8/8] Audio toggle tool ready"
echo "  To completely disable SCUF audio devices: sudo $INSTALL_DIR/tools/scuf-audio-toggle disable"
echo "  To re-enable: sudo $INSTALL_DIR/tools/scuf-audio-toggle enable"
echo "  To check status: sudo $INSTALL_DIR/tools/scuf-audio-toggle status"

echo ""
echo "======================================"
echo "Installation complete!"
echo "======================================"
echo ""
echo "You can now delete the cloned repository if you wish."
echo "Everything runs from $INSTALL_DIR and system directories."
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
echo "  # Disable/enable SCUF headphone audio:"
echo "  sudo $INSTALL_DIR/tools/scuf-audio-toggle disable"
echo "  sudo $INSTALL_DIR/tools/scuf-audio-toggle enable"
echo "  sudo $INSTALL_DIR/tools/scuf-audio-toggle status"
echo ""
echo "  # Uninstall:"
echo "  sudo bash $INSTALL_DIR/uninstall.sh"
echo ""
echo "Per-game profiles (add to game's launch options in Steam/Heroic):"
echo ""
echo "  scuf-profile PROFILENAME %command%"
echo ""
echo "  Profile switching (no restart needed):"
echo "  scuf-ctl ping                  # check driver is running"
echo "  scuf-ctl status                # show active profile + device info"
echo "  scuf-ctl profile PROFILENAME   # switch profile"
echo "  scuf-ctl profile default       # restore default"
echo ""
echo "  Define profiles in /etc/scuf-envision/config.ini:"
echo "  [profile.BIOSHOCK]"
echo "  BTN_TRIGGER_HAPPY1 = BTN_SOUTH"
echo ""
echo "Steam users: set this environment variable to prevent double input:"
echo ""
echo "  # bash/zsh (add to ~/.bashrc or ~/.zshrc):"
echo "  export SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05,0x1b1c/0x3a08"
echo ""
echo "  # fish (add to ~/.config/fish/config.fish):"
echo "  set -gx SDL_GAMECONTROLLER_IGNORE_DEVICES 0x1b1c/0x3a05,0x1b1c/0x3a08"
echo ""
