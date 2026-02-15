"""
Device discovery - find the SCUF Envision Pro V2 evdev nodes.

The controller exposes multiple USB interfaces:
  - Interface 1.3: Primary gamepad (HID Gamepad) -> this is what we want
  - Interface 1.4: Secondary input (Consumer Control, mouse/kbd emulation)
  - Interface 2.x: USB Audio (headphone jack) -> causes USB errors, not our problem

We scan /sys/class/input for evdev devices matching our VID:PID and identify
which one is the primary gamepad by checking for joystick (js*) handler siblings.
"""

import os
import glob
import logging
from pathlib import Path
from typing import Optional

from .constants import SCUF_VENDOR_ID, SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER

log = logging.getLogger(__name__)


class DiscoveredDevice:
    """Represents a discovered SCUF controller with its device paths."""

    def __init__(self, event_path: str, hidraw_path: Optional[str] = None,
                 secondary_event_paths: Optional[list] = None):
        self.event_path = event_path
        self.hidraw_path = hidraw_path
        self.secondary_event_paths = secondary_event_paths or []

    def __repr__(self):
        return (f"DiscoveredDevice(event={self.event_path}, "
                f"hidraw={self.hidraw_path}, "
                f"secondary={self.secondary_event_paths})")


def _read_sysfs(path: str) -> str:
    """Read a sysfs file, return empty string on failure."""
    try:
        return Path(path).read_text().strip()
    except (OSError, IOError):
        return ""


def _get_vid_pid(sysfs_path: str) -> tuple:
    """Get (vendor_id, product_id) as ints from a sysfs input device path."""
    vendor = _read_sysfs(os.path.join(sysfs_path, "device", "id", "vendor"))
    product = _read_sysfs(os.path.join(sysfs_path, "device", "id", "product"))
    try:
        return int(vendor, 16), int(product, 16)
    except ValueError:
        return 0, 0


def _has_joystick_handler(sysfs_path: str) -> bool:
    """Check if this input device has a js* (joystick) handler sibling."""
    handlers_path = os.path.join(sysfs_path, "device")
    try:
        for entry in os.listdir(handlers_path):
            if entry.startswith("js"):
                return True
        # Also check in the handlers file
        handlers_file = os.path.join(sysfs_path, "device", "capabilities", "abs")
        if os.path.exists(handlers_file):
            abs_caps = _read_sysfs(handlers_file)
            # A gamepad with sticks will have non-zero ABS capabilities
            if abs_caps and abs_caps != "0":
                return True
    except OSError:
        pass
    return False


def _find_event_node(sysfs_path: str) -> Optional[str]:
    """Find the /dev/input/eventN path for a sysfs input device."""
    device_name = os.path.basename(sysfs_path)
    dev_path = f"/dev/input/{device_name}"
    if os.path.exists(dev_path):
        return dev_path
    return None


def discover_scuf() -> Optional[DiscoveredDevice]:
    """
    Scan for SCUF Envision Pro V2 controllers.

    Returns a DiscoveredDevice with the primary gamepad event node,
    or None if no controller is found.
    """
    target_pids = {SCUF_PRODUCT_ID_WIRED}  # For now, wired only
    matching_events = []

    # Scan /sys/class/input/event* devices
    for sysfs_dir in sorted(glob.glob("/sys/class/input/event*")):
        vid, pid = _get_vid_pid(sysfs_dir)
        if vid == SCUF_VENDOR_ID and pid in target_pids:
            event_path = _find_event_node(sysfs_dir)
            if event_path:
                # Read device name for logging
                name = _read_sysfs(os.path.join(sysfs_dir, "device", "name"))
                has_js = _has_joystick_handler(sysfs_dir)
                log.debug(f"Found SCUF device: {event_path} name={name!r} joystick={has_js}")
                matching_events.append((event_path, has_js, name, sysfs_dir))

    if not matching_events:
        log.info("No SCUF Envision Pro V2 found")
        return None

    # Identify the primary gamepad: prefer the one with js* handler
    primary = None
    secondary = []

    for event_path, has_js, name, sysfs_dir in matching_events:
        if has_js and primary is None:
            primary = event_path
        else:
            secondary.append(event_path)

    # Fallback: if no js handler found, use the first Gamepad-type device
    if primary is None:
        # Try to identify by checking evdev capabilities
        import evdev
        for event_path, _, name, _ in matching_events:
            try:
                dev = evdev.InputDevice(event_path)
                caps = dev.capabilities()
                # A gamepad will have ABS_X and buttons
                if evdev.ecodes.EV_ABS in caps and evdev.ecodes.EV_KEY in caps:
                    abs_codes = [a[0] if isinstance(a, tuple) else a for a in caps[evdev.ecodes.EV_ABS]]
                    if evdev.ecodes.ABS_X in abs_codes:
                        primary = event_path
                        secondary = [e for e, _, _, _ in matching_events if e != event_path]
                        dev.close()
                        break
                dev.close()
            except (OSError, PermissionError):
                continue

    if primary is None:
        # Last resort: just use the first one
        primary = matching_events[0][0]
        secondary = [e for e, _, _, _ in matching_events[1:]]

    # Find hidraw device
    hidraw_path = _find_hidraw()

    log.info(f"SCUF primary gamepad: {primary}")
    if secondary:
        log.info(f"SCUF secondary inputs: {secondary}")
    if hidraw_path:
        log.info(f"SCUF hidraw: {hidraw_path}")

    return DiscoveredDevice(
        event_path=primary,
        hidraw_path=hidraw_path,
        secondary_event_paths=secondary,
    )


def _find_hidraw() -> Optional[str]:
    """Find the hidraw device for the SCUF controller."""
    for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent_path = os.path.join(hidraw_dir, "device", "uevent")
        uevent = _read_sysfs(uevent_path)
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                # Format: HID_ID=0003:00001B1C:00003A05
                parts = line.split("=", 1)[1].split(":")
                if len(parts) >= 3:
                    try:
                        vid = int(parts[1], 16)
                        pid = int(parts[2], 16)
                        if vid == SCUF_VENDOR_ID and pid == SCUF_PRODUCT_ID_WIRED:
                            dev_path = f"/dev/{os.path.basename(hidraw_dir)}"
                            if os.path.exists(dev_path):
                                return dev_path
                    except ValueError:
                        continue
    return None
