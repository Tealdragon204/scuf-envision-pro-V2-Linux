#!/bin/bash
# SCUF Envision Pro V2 — Enable headphone audio with working volume control
#
# The SCUF's USB audio "Headset" mixer has a broken dB range that makes
# hardware volume non-functional under PipeWire/WirePlumber. Additionally,
# the hardware mixer maxes out at -16 dB, making audio very quiet. This script:
#   1. Installs WirePlumber configs for software volume and gain boost
#   2. Sets the hardware mixer to maximum (software handles attenuation)
#   3. Removes old audio-disable workaround and stale PipeWire configs
#
# Run: sudo bash tools/setup_scuf_audio.sh
#
# After running, reboot or restart PipeWire/WirePlumber for changes to take effect.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
WP_CONF_DIR="/etc/wireplumber/wireplumber.conf.d"
WP_CONF_FILE="$WP_CONF_DIR/50-scuf-audio.conf"
WP_GAIN_FILE="$WP_CONF_DIR/50-scuf-gain.conf"
OLD_PW_GAIN_FILE="/etc/pipewire/pipewire.conf.d/50-scuf-gain.conf"
OLD_DISABLE_RULE="/etc/udev/rules.d/98-scuf-no-audio.rules"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash tools/setup_scuf_audio.sh"
    exit 1
fi

echo "======================================"
echo "SCUF Envision Pro V2 - Audio Setup"
echo "======================================"
echo ""

# Step 1: Remove old configs and workarounds
if [ -f "$OLD_DISABLE_RULE" ]; then
    echo "[1/5] Removing old audio-disable workaround..."
    rm -f "$OLD_DISABLE_RULE"
    echo "  Removed: $OLD_DISABLE_RULE"
else
    echo "[1/5] No old audio-disable workaround found (OK)"
fi
if [ -f "$OLD_PW_GAIN_FILE" ]; then
    echo "       Removing stale PipeWire gain config..."
    rm -f "$OLD_PW_GAIN_FILE"
    echo "  Removed: $OLD_PW_GAIN_FILE"
    echo "  (Gain filter is now a WirePlumber component instead)"
fi

# Step 2: Install WirePlumber config for software volume
echo "[2/5] Installing WirePlumber software volume config..."
mkdir -p "$WP_CONF_DIR"
cp "$REPO_DIR/50-scuf-audio.conf" "$WP_CONF_FILE"
echo "  Installed: $WP_CONF_FILE"
echo "  (Forces software volume mixing for SCUF audio)"

# Step 3: Install WirePlumber gain boost component
echo "[3/5] Installing WirePlumber gain boost filter..."
cp "$REPO_DIR/50-scuf-gain.conf" "$WP_GAIN_FILE"
echo "  Installed: $WP_GAIN_FILE"
echo "  (Smart filter: +12 dB gain, auto-links to SCUF sink only)"

# Step 4: Reload udev rules (for the mixer-max rule in 99-scuf-envision.rules)
echo "[4/5] Reloading udev rules..."
udevadm control --reload-rules
echo "  Done"

# Step 5: Set SCUF mixer to max right now (if controller is connected)
echo "[5/5] Setting SCUF hardware mixer to maximum..."
FOUND_CARD=false
for card_dir in /sys/class/sound/card*/; do
    card_num=$(basename "$card_dir" | sed 's/card//')
    # Walk up from the sound card to find USB device VID:PID
    real_path=$(readlink -f "$card_dir/device" 2>/dev/null || true)
    if [ -z "$real_path" ]; then
        continue
    fi
    # Check parent directories for idVendor/idProduct
    check_path="$real_path"
    for i in $(seq 1 6); do
        check_path=$(dirname "$check_path")
        if [ -f "$check_path/idVendor" ] && [ -f "$check_path/idProduct" ]; then
            vid=$(cat "$check_path/idVendor" 2>/dev/null)
            pid=$(cat "$check_path/idProduct" 2>/dev/null)
            if [ "$vid" = "1b1c" ] && { [ "$pid" = "3a05" ] || [ "$pid" = "3a08" ]; }; then
                if amixer -c "$card_num" sset Headset 100% unmute >/dev/null 2>&1; then
                    echo "  Set card $card_num (SCUF) Headset mixer to 100%"
                    FOUND_CARD=true
                else
                    echo "  Card $card_num (SCUF) found but could not set mixer"
                    echo "  (This is OK if the controller was just plugged in — the udev rule will handle it)"
                fi
            fi
            break
        fi
    done
done

if [ "$FOUND_CARD" = false ]; then
    echo "  No SCUF sound card found (controller not connected or audio interface not loaded)"
    echo "  The udev rule will set the mixer automatically when you plug in the controller."
fi

echo ""
echo "======================================"
echo "Audio setup complete!"
echo "======================================"
echo ""
echo "To apply changes, either:"
echo "  1. Reboot (recommended), or"
echo "  2. Restart PipeWire + WirePlumber:"
echo "     systemctl --user restart pipewire wireplumber"
echo "     (run as your normal user, NOT as root)"
echo ""
echo "After restart, the SCUF headphone volume slider should work normally"
echo "with a +12 dB gain boost to compensate for the quiet hardware output."
echo ""
echo "To adjust the gain: edit $WP_GAIN_FILE"
echo "  Change '\"Gain\" = 12.0' to a different value (6, 16, 18, etc.)"
echo "  Then restart PipeWire/WirePlumber or reboot."
echo ""
echo "To undo this setup:"
echo "  sudo rm $WP_CONF_FILE $WP_GAIN_FILE"
echo "  sudo udevadm control --reload-rules"
echo "  (then reboot or restart PipeWire/WirePlumber)"
