#!/usr/bin/env python3
"""
SCUF Envision Pro V2 Diagnostic Tool

Reads raw events from the controller and prints them in human-readable format.
Use this to verify button mappings and axis ranges before running the driver.

Usage:
    sudo python3 tools/diag.py

Press Ctrl+C to exit.
"""

import sys
import os
import glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evdev
from evdev import ecodes, categorize
from scuf_envision.discovery import discover_scuf, _get_vid_pid, _has_joystick_handler, _event_number
from scuf_envision.constants import BUTTON_MAP, AXIS_MAP, SCUF_VENDOR_ID, SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER

# Human-readable names for the SCUF's actual physical buttons
SCUF_BUTTON_NAMES = {
    ecodes.BTN_SOUTH: "A (BTN_SOUTH)",
    ecodes.BTN_EAST:  "B (BTN_EAST)",
    ecodes.BTN_C:     "X (BTN_C) -> should be BTN_NORTH (BTN_X)",
    ecodes.BTN_NORTH: "Y (BTN_NORTH) -> should be BTN_WEST (BTN_Y)",
    ecodes.BTN_WEST:  "LB (BTN_WEST) -> should be BTN_TL",
    ecodes.BTN_Z:     "RB (BTN_Z) -> should be BTN_TR",
    ecodes.BTN_TL:    "Select/Back (BTN_TL)",
    ecodes.BTN_TR:    "Start/Menu (BTN_TR)",
    ecodes.BTN_TL2:   "L3/LS Click (BTN_TL2) -> should be BTN_THUMBL",
    ecodes.BTN_TR2:   "R3/RS Click (BTN_TR2) -> should be BTN_THUMBR",
    ecodes.BTN_MODE:  "Guide/Xbox (BTN_MODE)",
    ecodes.BTN_TRIGGER_HAPPY1: "Paddle 1",
    ecodes.BTN_TRIGGER_HAPPY2: "Paddle 2",
    ecodes.BTN_TRIGGER_HAPPY3: "Paddle 3",
    ecodes.BTN_TRIGGER_HAPPY4: "Paddle 4",
}

SCUF_AXIS_NAMES = {
    ecodes.ABS_X:      "Left Stick X (correct)",
    ecodes.ABS_Y:      "Left Stick Y (correct)",
    ecodes.ABS_Z:      "Right Stick X (ABS_Z -> should be ABS_RX)",
    ecodes.ABS_RX:     "Left Trigger (ABS_RX -> should be ABS_Z)",
    ecodes.ABS_RY:     "Right Trigger (ABS_RY -> should be ABS_RZ)",
    ecodes.ABS_RZ:     "Right Stick Y (ABS_RZ -> should be ABS_RY)",
    ecodes.ABS_HAT0X:  "D-pad X (correct)",
    ecodes.ABS_HAT0Y:  "D-pad Y (correct)",
    ecodes.ABS_MISC:   "ABS_MISC (not a gamepad axis)",
}


def scan_all_scuf_devices():
    """Show every event device matching SCUF VID:PID with its capabilities."""
    print("Scanning all SCUF event devices...")
    print()

    target_pids = {SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER}
    sysfs_dirs = sorted(glob.glob("/sys/class/input/event*"), key=_event_number)
    found = []
    wired_count = 0
    wireless_count = 0

    for sysfs_dir in sysfs_dirs:
        vid, pid = _get_vid_pid(sysfs_dir)
        if vid == SCUF_VENDOR_ID and pid in target_pids:
            event_name = os.path.basename(sysfs_dir)
            event_path = f"/dev/input/{event_name}"
            has_js = _has_joystick_handler(sysfs_dir)
            found.append((event_path, has_js))
            if pid == SCUF_PRODUCT_ID_WIRED:
                wired_count += 1
            else:
                wireless_count += 1

            try:
                dev = evdev.InputDevice(event_path)
                caps = dev.capabilities(verbose=False)
                dev_name = dev.name
                dev_phys = dev.phys
                dev.close()
            except (OSError, PermissionError) as e:
                print(f"  {event_path}: cannot open ({e})")
                continue

            conn_label = "WIRELESS" if pid == SCUF_PRODUCT_ID_RECEIVER else "WIRED"
            js_label = " [JOYSTICK]" if has_js else ""
            print(f"  {event_path}{js_label} ({conn_label})")
            print(f"    Name: {dev_name}")
            print(f"    Phys: {dev_phys}")

            # Summarize capabilities
            if ecodes.EV_KEY in caps:
                btn_names = []
                for code in caps[ecodes.EV_KEY]:
                    name = ecodes.BTN.get(code) or ecodes.KEY.get(code) or f"0x{code:03x}"
                    if isinstance(name, list):
                        name = name[0]
                    btn_names.append(name)
                print(f"    Buttons ({len(btn_names)}): {', '.join(str(b) for b in btn_names[:15])}"
                      + (" ..." if len(btn_names) > 15 else ""))
            else:
                print("    Buttons: none")

            if ecodes.EV_ABS in caps:
                axis_names = []
                for entry in caps[ecodes.EV_ABS]:
                    code = entry[0] if isinstance(entry, tuple) else entry
                    name = ecodes.ABS.get(code, f"0x{code:02x}")
                    if isinstance(name, list):
                        name = name[0]
                    axis_names.append(name)
                print(f"    Axes ({len(axis_names)}): {', '.join(str(a) for a in axis_names)}")
            else:
                print("    Axes: none")

            print()

    # Print per-connection-type summary
    print(f"Searching for wired controller (1b1c:{SCUF_PRODUCT_ID_WIRED:04x})... "
          f"{'found ' + str(wired_count) + ' device(s)' if wired_count else 'not found'}")
    print(f"Searching for wireless receiver (1b1c:{SCUF_PRODUCT_ID_RECEIVER:04x})... "
          f"{'found ' + str(wireless_count) + ' device(s)' if wireless_count else 'not found'}")
    print()

    # Also show hidraw devices
    print("SCUF hidraw devices:")
    for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent_path = os.path.join(hidraw_dir, "device", "uevent")
        try:
            uevent = open(uevent_path).read()
        except (OSError, IOError):
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                parts = line.split("=", 1)[1].split(":")
                if len(parts) >= 3:
                    try:
                        vid = int(parts[1], 16)
                        pid = int(parts[2], 16)
                    except ValueError:
                        continue
                    if vid == SCUF_VENDOR_ID and pid in (SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER):
                        pid_label = "wireless" if pid == SCUF_PRODUCT_ID_RECEIVER else "wired"
                        dev_path = f"/dev/{os.path.basename(hidraw_dir)}"
                        print(f"  {dev_path} ({pid_label})")
    print()

    return found


def main():
    print("=" * 60)
    print("SCUF Envision Pro V2 - Diagnostic Tool")
    print("=" * 60)
    print()

    # First: show ALL matching devices so the user can see what's detected
    all_devices = scan_all_scuf_devices()

    # Then: run discovery to show what the driver would select
    print("-" * 60)
    print("Running device discovery (what the driver will use)...")
    print("-" * 60)
    print()

    discovered = discover_scuf()
    if discovered is None:
        print("ERROR: No SCUF controller found!")
        print("  - Is the controller plugged in via USB?")
        print("  - Check: lsusb | grep 1b1c")
        sys.exit(1)

    print(f"Primary device:    {discovered.event_path}")
    print(f"HID raw device:    {discovered.hidraw_path or 'not found'}")
    print(f"Connection type:   {discovered.connection_type}")
    print(f"Secondary devices: {discovered.secondary_event_paths or 'none'}")
    print()

    dev = evdev.InputDevice(discovered.event_path)
    print(f"Device name: {dev.name}")
    print(f"Device path: {dev.path}")
    print(f"Phys:        {dev.phys}")
    print()

    # Print capabilities
    caps = dev.capabilities(verbose=True)
    print("Capabilities:")
    for ev_type, codes in caps.items():
        if ev_type[0] == 0:  # Skip EV_SYN
            continue
        print(f"  {ev_type[1]} ({ev_type[0]}):")
        for code_info in codes:
            if isinstance(code_info, tuple) and len(code_info) == 2:
                code, absinfo = code_info
                print(f"    {code}: {absinfo}")
            else:
                print(f"    {code_info}")
    print()

    # Check if the selected device looks like a real gamepad
    raw_caps = dev.capabilities(verbose=False)
    has_abs_x = False
    if ecodes.EV_ABS in raw_caps:
        for entry in raw_caps[ecodes.EV_ABS]:
            code = entry[0] if isinstance(entry, tuple) else entry
            if code == ecodes.ABS_X:
                has_abs_x = True
    has_buttons = ecodes.EV_KEY in raw_caps

    if not (has_abs_x and has_buttons):
        print("WARNING: Selected device does NOT look like a gamepad!")
        print("         It's missing ABS_X/ABS_Y axes or gamepad buttons.")
        print("         The driver may not work with this device.")
        print("         Check the device list above - the correct device")
        print("         should be the one marked [JOYSTICK].")
        print()

    print("=" * 60)
    print("Press buttons and move sticks to see raw events.")
    print("Press Ctrl+C to exit.")
    print("=" * 60)
    print()

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_SYN:
                continue

            if event.type == ecodes.EV_KEY:
                name = SCUF_BUTTON_NAMES.get(event.code, f"UNKNOWN (0x{event.code:03x})")
                state = "PRESSED" if event.value == 1 else "RELEASED" if event.value == 0 else f"value={event.value}"
                print(f"BUTTON: {name:45s} {state}")

            elif event.type == ecodes.EV_ABS:
                name = SCUF_AXIS_NAMES.get(event.code, f"UNKNOWN (0x{event.code:02x})")
                print(f"AXIS:   {name:45s} value={event.value}")

            else:
                print(f"OTHER:  type={event.type} code={event.code} value={event.value}")

    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
