#!/bin/bash
# SCUF Envision Pro V2 Linux Driver - Uninstaller

set -e

echo "======================================"
echo "SCUF Envision Pro V2 - Uninstaller"
echo "======================================"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash uninstall.sh"
    exit 1
fi

echo "[1/6] Stopping and disabling service..."
systemctl stop scuf-envision.service 2>/dev/null || true
systemctl disable scuf-envision.service 2>/dev/null || true
rm -f /etc/systemd/system/scuf-envision.service
systemctl daemon-reload

echo "[2/6] Re-enabling SCUF audio if it was disabled..."
if [ -f /etc/scuf-envision/config.ini ]; then
    if python3 -c "
import configparser, sys
c = configparser.ConfigParser()
c.read('/etc/scuf-envision/config.ini')
sys.exit(0 if c.getboolean('audio', 'disabled', fallback=False) else 1)
" 2>/dev/null; then
        python3 -c "
import sys; sys.path.insert(0, '/opt/scuf-envision')
from scuf_envision.audio_control import rebind_scuf_audio
rebind_scuf_audio()
" 2>/dev/null && echo "  Re-enabled SCUF audio (was disabled)" || echo "  Could not re-enable audio (device may not be connected)"
    else
        echo "  Audio was not disabled, nothing to do"
    fi
else
    echo "  No config file found, skipping"
fi

echo "[3/6] Removing udev rules..."
rm -f /etc/udev/rules.d/99-scuf-envision.rules
udevadm control --reload-rules

echo "[4/6] Removing audio configs..."
rm -f /etc/wireplumber/wireplumber.conf.d/50-scuf-audio.conf
rm -f /etc/wireplumber/wireplumber.conf.d/50-scuf-gain.conf   # legacy, from older installs
rm -f /etc/pipewire/pipewire.conf.d/50-scuf-gain.conf         # legacy, from older installs
echo "  Removed WirePlumber and PipeWire audio configs (if present)"

echo "[5/6] Removing CLI tool symlink..."
rm -f /usr/local/bin/scuf-audio-toggle

echo "[6/6] Removing installed files..."
rm -rf /opt/scuf-envision

echo ""
echo "Uninstall complete."
echo "Note: python-evdev and uinput module were not removed."
echo "Note: /etc/scuf-envision/ was preserved. Remove manually if desired:"
echo "  sudo rm -rf /etc/scuf-envision"
echo "Restart PipeWire/WirePlumber or reboot to apply audio changes."
