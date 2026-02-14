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

echo "[1/3] Stopping and disabling service..."
systemctl stop scuf-envision.service 2>/dev/null || true
systemctl disable scuf-envision.service 2>/dev/null || true
rm -f /etc/systemd/system/scuf-envision.service
systemctl daemon-reload

echo "[2/3] Removing udev rules..."
rm -f /etc/udev/rules.d/99-scuf-envision.rules
udevadm control --reload-rules

echo "[3/3] Removing installed files..."
rm -rf /opt/scuf-envision

echo ""
echo "Uninstall complete."
echo "Note: python-evdev and uinput module were not removed."
