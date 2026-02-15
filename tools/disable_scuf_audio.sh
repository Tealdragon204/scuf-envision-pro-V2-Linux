#!/bin/bash
# Workaround: Disable Linux USB audio driver from claiming the SCUF's audio interfaces.
#
# The SCUF Envision Pro V2 exposes USB audio endpoints (headphone jack) that
# the Linux snd-usb-audio driver fails to configure, causing repeated errors:
#   usb 3-6: 2:1: cannot set freq 96000 to ep 0x3
#   usb 3-6: 2:1: usb_set_interface failed (-71)
#
# These errors can destabilize the USB connection and cause the entire controller
# to disconnect. This script creates a udev rule that prevents snd-usb-audio
# from binding to the SCUF's audio interfaces.
#
# Run: sudo bash tools/disable_scuf_audio.sh

set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash tools/disable_scuf_audio.sh"
    exit 1
fi

RULE_FILE="/etc/udev/rules.d/98-scuf-no-audio.rules"

cat > "$RULE_FILE" << 'EOF'
# Prevent snd-usb-audio from claiming SCUF Envision Pro V2 audio interfaces.
# This stops the USB errors that can crash the controller connection.
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="1b1c", ATTR{idProduct}=="3a05", \
  RUN+="/bin/sh -c 'echo 0 > /sys$devpath/bInterfaceNumber_2_authorized'"
EOF

echo "Created: $RULE_FILE"
echo ""
echo "This prevents the USB audio driver from claiming the SCUF's audio interfaces."
echo "The controller headphone jack will NOT work, but the gamepad will be more stable."
echo ""
echo "Reloading udev rules..."
udevadm control --reload-rules
echo "Done. Unplug and replug the controller to apply."
echo ""
echo "To undo: sudo rm $RULE_FILE && sudo udevadm control --reload-rules"
