"""
Device discovery - find the SCUF Envision Pro V2 evdev nodes.

The controller exposes multiple USB interfaces:
  - Interface 3 (if03): Primary gamepad (HID Gamepad) -> this is what we want
  - Interface 4 (if04): Secondary input (Consumer Control, menu buttons)
  - Interface 2.x: USB Audio (headphone jack) -> causes USB errors

Event and hidraw device numbers are assigned dynamically by the kernel
(e.g. /dev/input/event7 today might be event22 tomorrow). We identify
the correct device by:
  1. Matching VID:PID via sysfs
  2. Checking for a js* (joystick) handler sibling
  3. Verifying actual gamepad capabilities (ABS_X, ABS_Y, EV_KEY)
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
                 secondary_event_paths: Optional[list] = None,
                 connection_type: str = "wired"):
        self.event_path = event_path
        self.hidraw_path = hidraw_path
        self.secondary_event_paths = secondary_event_paths or []
        self.connection_type = connection_type

    def __repr__(self):
        return (f"DiscoveredDevice(event={self.event_path}, "
                f"hidraw={self.hidraw_path}, "
                f"secondary={self.secondary_event_paths}, "
                f"type={self.connection_type})")


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


def _event_number(sysfs_path: str) -> int:
    """Extract the numeric part of an event device path for sorting."""
    basename = os.path.basename(sysfs_path)
    try:
        return int(basename.replace("event", ""))
    except ValueError:
        return 999999


def _has_joystick_handler(sysfs_path: str) -> bool:
    """
    Check if this input device has a js* (joystick) handler sibling.

    In sysfs, /sys/class/input/eventN/device/ is the parent input device
    directory. If the same parent also has a jsN entry, this is a joystick.
    This is the most reliable indicator for the gamepad evdev node.
    """
    device_dir = os.path.join(sysfs_path, "device")
    try:
        for entry in os.listdir(device_dir):
            if entry.startswith("js"):
                return True
    except OSError:
        pass
    return False


def _has_gamepad_capabilities(event_path: str) -> bool:
    """
    Check if an evdev device has actual gamepad capabilities.

    A real gamepad must have:
      - EV_ABS with at least ABS_X and ABS_Y (analog sticks)
      - EV_KEY with at least some gamepad buttons
    """
    import evdev
    try:
        dev = evdev.InputDevice(event_path)
        caps = dev.capabilities()
        dev.close()

        # Must have both axes and buttons
        if evdev.ecodes.EV_ABS not in caps or evdev.ecodes.EV_KEY not in caps:
            return False

        # Check for analog stick axes (ABS_X and ABS_Y at minimum)
        abs_codes = set()
        for entry in caps[evdev.ecodes.EV_ABS]:
            code = entry[0] if isinstance(entry, tuple) else entry
            abs_codes.add(code)

        if evdev.ecodes.ABS_X not in abs_codes or evdev.ecodes.ABS_Y not in abs_codes:
            return False

        # Check for gamepad buttons (at least one from BTN_SOUTH..BTN_THUMBR range)
        btn_codes = set(caps[evdev.ecodes.EV_KEY])
        gamepad_buttons = {
            evdev.ecodes.BTN_SOUTH, evdev.ecodes.BTN_EAST,
            evdev.ecodes.BTN_NORTH, evdev.ecodes.BTN_WEST,
            evdev.ecodes.BTN_C, evdev.ecodes.BTN_Z,
            evdev.ecodes.BTN_TL, evdev.ecodes.BTN_TR,
            evdev.ecodes.BTN_TL2, evdev.ecodes.BTN_TR2,
        }
        if not btn_codes & gamepad_buttons:
            return False

        return True
    except (OSError, PermissionError):
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

    Identification strategy (in priority order):
      1. Find all event devices matching our VID:PID
      2. Prefer the one with a js* (joystick) handler sibling
      3. If no js handler, pick the one with real gamepad capabilities
      4. Everything else is marked as secondary

    Returns a DiscoveredDevice with the primary gamepad event node,
    or None if no controller is found.
    """
    target_pids = {SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER}
    matching_events = []

    # Scan /sys/class/input/event* devices, sorted numerically
    sysfs_dirs = sorted(glob.glob("/sys/class/input/event*"), key=_event_number)
    wired_count = 0
    wireless_count = 0
    for sysfs_dir in sysfs_dirs:
        vid, pid = _get_vid_pid(sysfs_dir)
        if vid == SCUF_VENDOR_ID and pid in target_pids:
            event_path = _find_event_node(sysfs_dir)
            if event_path:
                name = _read_sysfs(os.path.join(sysfs_dir, "device", "name"))
                has_js = _has_joystick_handler(sysfs_dir)
                if pid == SCUF_PRODUCT_ID_WIRED:
                    wired_count += 1
                else:
                    wireless_count += 1
                log.debug(f"Found SCUF event device: {event_path} "
                          f"name={name!r} has_joystick={has_js} pid=0x{pid:04x}")
                matching_events.append((event_path, has_js, name, sysfs_dir, pid))

    # Report per-connection-type search results
    log.info(f"Searching for wired controller (1b1c:{SCUF_PRODUCT_ID_WIRED:04x})... "
             f"{'found ' + str(wired_count) + ' device(s)' if wired_count else 'not found'}")
    log.info(f"Searching for wireless receiver (1b1c:{SCUF_PRODUCT_ID_RECEIVER:04x})... "
             f"{'found ' + str(wireless_count) + ' device(s)' if wireless_count else 'not found'}")

    if not matching_events:
        return None

    # --- Select the primary gamepad ---

    primary = None
    secondary = []

    # Strategy 1: Pick the device with a js* handler (most reliable)
    for event_path, has_js, name, sysfs_dir, pid in matching_events:
        if has_js:
            if primary is None:
                primary = event_path
                log.info(f"Primary gamepad (js handler): {event_path}")
            else:
                secondary.append(event_path)
        else:
            secondary.append(event_path)

    # Strategy 2: If no js handler found, check actual evdev capabilities
    if primary is None:
        log.debug("No js handler found, checking evdev capabilities...")
        for event_path, _, name, _, _ in matching_events:
            if _has_gamepad_capabilities(event_path):
                primary = event_path
                secondary = [e for e, _, _, _, _ in matching_events if e != event_path]
                log.info(f"Primary gamepad (capabilities match): {event_path}")
                break

    # Strategy 3: Last resort - just use the first device
    if primary is None:
        primary = matching_events[0][0]
        secondary = [e for e, _, _, _, _ in matching_events[1:]]
        log.warning(f"Primary gamepad (fallback, first device): {primary}")

    # Find hidraw device for the gamepad interface
    hidraw_path = _find_hidraw_for_gamepad(primary)

    # Determine connection type from the matched PID
    conn_type = "wired"
    for ep, _, _, _, matched_pid in matching_events:
        if ep == primary:
            if matched_pid == SCUF_PRODUCT_ID_RECEIVER:
                conn_type = "wireless"
            break

    if secondary:
        log.info(f"Secondary inputs: {secondary}")
    if hidraw_path:
        log.info(f"HID raw device: {hidraw_path}")
    log.info(f"Connection type: {conn_type}")

    return DiscoveredDevice(
        event_path=primary,
        hidraw_path=hidraw_path,
        secondary_event_paths=secondary,
        connection_type=conn_type,
    )


def _find_hidraw_for_gamepad(event_path: str) -> Optional[str]:
    """
    Find the hidraw device that shares the same USB interface as the
    primary gamepad event device.

    Falls back to the first VID:PID-matching hidraw if interface matching
    fails (still correct when only one hidraw matches).
    """
    # Try to find which USB interface the event device belongs to
    # by resolving the sysfs symlink chain
    event_name = os.path.basename(event_path)
    sysfs_link = f"/sys/class/input/{event_name}"
    try:
        real_path = os.path.realpath(sysfs_link)
    except OSError:
        real_path = ""

    # Walk up to find the USB interface directory (contains "bInterfaceNumber")
    gamepad_interface_dir = None
    check_path = real_path
    for _ in range(10):  # max depth
        check_path = os.path.dirname(check_path)
        if not check_path or check_path == "/":
            break
        if os.path.exists(os.path.join(check_path, "bInterfaceNumber")):
            gamepad_interface_dir = check_path
            break

    # Now find hidraw devices - prefer the one on the same USB interface
    first_match = None
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
                    except ValueError:
                        continue
                    if vid == SCUF_VENDOR_ID and pid in (SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER):
                        dev_path = f"/dev/{os.path.basename(hidraw_dir)}"
                        if not os.path.exists(dev_path):
                            continue

                        if first_match is None:
                            first_match = dev_path

                        # Check if this hidraw is on the same USB interface
                        if gamepad_interface_dir:
                            hidraw_real = os.path.realpath(hidraw_dir)
                            if gamepad_interface_dir in hidraw_real:
                                log.debug(f"hidraw interface match: {dev_path}")
                                return dev_path

    # Fallback: return the first VID:PID match
    return first_match
