#!/usr/bin/env python3
"""
SCUF Envision Pro V2 Diagnostic Tool

Reads raw events from the controller and prints them in human-readable format.
Use this to verify button mappings and axis ranges before running the driver.

Usage:
    sudo python3 tools/diag.py
    sudo python3 tools/diag.py --deadzone [--profile NAME]

Press Ctrl+C to exit.
"""

import sys
import os
import glob
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evdev
from evdev import ecodes, categorize
from scuf_envision.discovery import discover_scuf, discover_scuf_with_retry, _get_vid_pid, _has_joystick_handler, _event_number
from scuf_envision.constants import HID_BUTTON_MAP, SCUF_VENDOR_ID, SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER, VIRTUAL_DEVICE_NAME

# ANSI color codes
RED = "\033[91m"
RESET = "\033[0m"

# All digital buttons and axes come from HID raw — evdev is grabbed/suppressed only
RAW_WRONG_BUTTONS: set = set()
RAW_WRONG_AXES: set = set()

# Buttons the SCUF exposes via evdev (limited set; driver reads all buttons via HID raw)
SCUF_BUTTON_NAMES = {
    ecodes.BTN_SOUTH:  "A",
    ecodes.BTN_EAST:   "B",
    ecodes.BTN_NORTH:  "X",
    ecodes.BTN_WEST:   "Y",
    ecodes.BTN_TL:     "LB",
    ecodes.BTN_TR:     "RB",
    ecodes.BTN_SELECT: "Select/Back",
    ecodes.BTN_START:  "Start/Menu",
    ecodes.BTN_THUMBL: "L3",
    ecodes.BTN_THUMBR: "R3",
    ecodes.BTN_MODE:   "Home/Xbox",
    # NOTE: paddles (P1-P4), SAX (S1/S2), G-keys (G1-G5), Profile button
    # are NOT visible in evdev — read from HID raw by the driver.
}

# Axes the SCUF exposes via evdev (scrambled codes; driver reads all axes via HID raw)
SCUF_AXIS_NAMES = {
    ecodes.ABS_X:      "Left Stick X",
    ecodes.ABS_Y:      "Left Stick Y",
    ecodes.ABS_Z:      "Right Stick X (scrambled — driver reads via HID raw)",
    ecodes.ABS_RX:     "Left Trigger (scrambled — driver reads via HID raw)",
    ecodes.ABS_RY:     "Right Trigger (scrambled — driver reads via HID raw)",
    ecodes.ABS_RZ:     "Right Stick Y (scrambled — driver reads via HID raw)",
    ecodes.ABS_HAT0X:  "D-pad X (driver reads via HID bitmask)",
    ecodes.ABS_HAT0Y:  "D-pad Y (driver reads via HID bitmask)",
    ecodes.ABS_MISC:   "ABS_MISC (not a gamepad axis)",
}

# Names for the remapped virtual Xbox gamepad output
VIRTUAL_BUTTON_NAMES = {
    ecodes.BTN_SOUTH:  "A",
    ecodes.BTN_EAST:   "B",
    ecodes.BTN_NORTH:  "X",
    ecodes.BTN_WEST:   "Y",
    ecodes.BTN_TL:     "LB",
    ecodes.BTN_TR:     "RB",
    ecodes.BTN_SELECT: "Select/Back",
    ecodes.BTN_START:  "Start/Menu",
    ecodes.BTN_THUMBL: "L3",
    ecodes.BTN_THUMBR: "R3",
    ecodes.BTN_MODE:   "Home/Xbox",
    ecodes.BTN_TRIGGER_HAPPY1:  "Paddle P1 (rear bottom-left)",
    ecodes.BTN_TRIGGER_HAPPY2:  "Paddle P2 (rear bottom-right)",
    ecodes.BTN_TRIGGER_HAPPY3:  "Paddle P3 (rear top-left)",
    ecodes.BTN_TRIGGER_HAPPY4:  "Paddle P4 (rear top-right)",
    ecodes.BTN_TRIGGER_HAPPY5:  "SAX S1 (left grip)",
    ecodes.BTN_TRIGGER_HAPPY6:  "SAX S2 (right grip)",
    ecodes.BTN_TRIGGER_HAPPY7:  "G1",
    ecodes.BTN_TRIGGER_HAPPY8:  "G2",
    ecodes.BTN_TRIGGER_HAPPY9:  "G3",
    ecodes.BTN_TRIGGER_HAPPY10: "G4",
    ecodes.BTN_TRIGGER_HAPPY11: "G5",
    ecodes.BTN_TRIGGER_HAPPY12: "Profile button",
}

VIRTUAL_AXIS_NAMES = {
    ecodes.ABS_X:     "Left Stick X",
    ecodes.ABS_Y:     "Left Stick Y",
    ecodes.ABS_RX:    "Right Stick X",
    ecodes.ABS_RY:    "Right Stick Y",
    ecodes.ABS_Z:     "Left Trigger",
    ecodes.ABS_RZ:    "Right Trigger",
    ecodes.ABS_HAT0X: "D-pad X",
    ecodes.ABS_HAT0Y: "D-pad Y",
}


def find_virtual_device():
    """Find the bridge's virtual Xbox gamepad if it exists."""
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if dev.name == VIRTUAL_DEVICE_NAME:
                return dev
            dev.close()
        except (OSError, PermissionError):
            continue
    return None


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


_STICK_AXIS_LABELS = {
    ecodes.ABS_X:  "LEFT  X",
    ecodes.ABS_Y:  "LEFT  Y",
    ecodes.ABS_RX: "RIGHT X",
    ecodes.ABS_RY: "RIGHT Y",
}
_TRIGGER_AXIS_LABELS = {
    ecodes.ABS_Z:  "L.TRIG",
    ecodes.ABS_RZ: "R.TRIG",
}


def _get_active_profile() -> str | None:
    """Query the running driver for the active profile name via IPC socket."""
    import socket as _socket, json
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect("/run/scuf-envision/ipc.sock")
        sock.sendall(b"status")
        data = sock.recv(4096).decode().strip()
        sock.close()
        return json.loads(data).get("profile")
    except Exception:
        return None


def run_deadzone_mode(profile_name=None):
    """Show current deadzone config and live filtered axis output."""
    from scuf_envision.config import input_params
    from scuf_envision import __version__

    print("=" * 65)
    print(f"SCUF Envision Pro V2 - Deadzone Diagnostic v{__version__}")
    print("=" * 65)
    print()

    # Auto-detect active profile from running driver if not overridden by --profile
    explicit = profile_name is not None
    if not explicit:
        profile_name = _get_active_profile()

    p = input_params(profile_name)

    if profile_name:
        section = f"[profile.{profile_name}.input]"
        source = "explicit --profile" if explicit else "detected from running driver"
    else:
        section = "[input]"
        source = "global (driver not running or no profile active)"
    print(f"Active profile:      {profile_name or 'default'} ({source})")
    print(f"Config section used: {section}")
    print()
    print("  Hardware deadzone (firmware registers, 0–15):")
    print(f"    Left  stick:   {p['left_stick_deadzone_hw']}")
    print(f"    Right stick:   {p['right_stick_deadzone_hw']}")
    print(f"    Left  trigger: {p['left_trigger_deadzone_hw']}")
    print(f"    Right trigger: {p['right_trigger_deadzone_hw']}")
    print()
    print("  Software deadzone (driver, applied after HW):")
    print(f"    Left  stick:   {p['left_stick_deadzone_sw']}  (of ±32767)")
    print(f"    Right stick:   {p['right_stick_deadzone_sw']}  (of ±32767)")
    print(f"    Left  trigger: {p['left_trigger_deadzone_sw']}  (of 0–1023)")
    print(f"    Right trigger: {p['right_trigger_deadzone_sw']}  (of 0–1023)")
    print()
    print("  Anti-deadzone (output floor, 0 = off):")
    print(f"    Left  stick:   {p['left_stick_anti_deadzone']}")
    print(f"    Right stick:   {p['right_stick_anti_deadzone']}")
    print()
    print(f"  Jitter threshold: {p['jitter_threshold']}")
    print()

    # Hardware DZ note — write-only registers
    print("  NOTE: Hardware deadzone registers are write-only (no read-back).")
    print("  Verify they were sent by checking driver logs:")
    print("    journalctl -u scuf-envision | grep 'HW deadzones'")
    print()

    # Check flat=0 on virtual device
    virtual = find_virtual_device()
    if virtual:
        raw_caps = virtual.capabilities(verbose=False)
        abs_entries = raw_caps.get(ecodes.EV_ABS, [])
        flat_val = None
        for entry in abs_entries:
            if isinstance(entry, tuple) and entry[0] == ecodes.ABS_X:
                flat_val = entry[1].flat
                break
        if flat_val is not None:
            status = "PASS" if flat_val == 0 else f"WARN (flat={flat_val}, expected 0)"
            print(f"  uinput flat on ABS_X: {status}")
        print()
    else:
        print("  Bridge not running — skipping uinput flat check.")
        print()

    # Live event display
    dev = virtual or None
    if dev is None:
        from scuf_envision.discovery import discover_scuf
        discovered = discover_scuf()
        if discovered:
            try:
                dev = evdev.InputDevice(discovered.event_path)
            except OSError:
                pass

    if dev is None:
        print("No device found — cannot show live axis output.")
        return

    mode = "virtual (filtered)" if virtual else "raw (unfiltered)"
    print(f"  Reading from: {dev.path} [{mode}]")
    print("  Move sticks and triggers to see values.")
    print("  Press Ctrl+C to exit.")
    print()
    print(f"  {'AXIS':<10}  {'VALUE':>8}  {'NOTE'}")
    print("  " + "-" * 40)

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_SYN:
                continue
            if event.type != ecodes.EV_ABS:
                continue

            code, val = event.code, event.value
            if code in _STICK_AXIS_LABELS:
                label = _STICK_AXIS_LABELS[code]
                note = "(deadzone)" if val == 0 else ""
                # Show anti-dz floor reminder when output is non-zero
                anti = (p['left_stick_anti_deadzone'] if code in (ecodes.ABS_X, ecodes.ABS_Y)
                        else p['right_stick_anti_deadzone'])
                if val != 0 and anti and abs(val) < anti:
                    note = f"(below anti-dz floor {anti})"
                print(f"  {label:<10}  {val:>8}  {note}")
            elif code in _TRIGGER_AXIS_LABELS:
                label = _TRIGGER_AXIS_LABELS[code]
                print(f"  {label:<10}  {val:>8}")
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        if not virtual:
            dev.close()


def main():
    from scuf_envision import __version__

    parser = argparse.ArgumentParser(
        description="SCUF Envision Pro V2 Diagnostic Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--deadzone", action="store_true",
                        help="Show deadzone config and live filtered axis output")
    parser.add_argument("--profile", metavar="NAME", default=None,
                        help="Profile name to load config from (used with --deadzone)")
    args = parser.parse_args()

    if args.deadzone:
        run_deadzone_mode(profile_name=args.profile)
        return

    print("=" * 60)
    print(f"SCUF Envision Pro V2 - Diagnostic Tool v{__version__}")
    print("=" * 60)
    print()

    # First: show ALL matching devices so the user can see what's detected
    all_devices = scan_all_scuf_devices()

    # Then: run discovery to show what the driver would select
    print("-" * 60)
    print("Running device discovery (what the driver will use)...")
    print("-" * 60)
    print()

    discovered = discover_scuf_with_retry()
    if discovered is None:
        print("ERROR: No SCUF controller found after 30s!")
        print("  - Is the controller plugged in via USB or wireless receiver connected?")
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

    # Check if the bridge is running (virtual device exists)
    virtual_dev = find_virtual_device()
    if virtual_dev:
        print("!" * 60)
        print("NOTE: The SCUF bridge driver is currently running.")
        print(f"  Virtual device: {virtual_dev.path} ({virtual_dev.name})")
        print()
        # Show active profile from IPC if available
        try:
            import subprocess, json
            raw = subprocess.check_output(["scuf-ctl", "status"], timeout=2)
            data = json.loads(raw)
            print(f"  Active profile: {data.get('profile', 'default')}")
            profiles = data.get("profiles", [])
            if len(profiles) > 1:
                print(f"  Available:      {', '.join(profiles)}")
            print()
        except Exception:
            pass
        print("The bridge has exclusive access to the physical controller,")
        print("so raw events will not appear here. Switching to virtual")
        print("device mode to show the bridge's remapped output instead.")
        print("!" * 60)
        print()
        dev.close()
        dev = virtual_dev
        button_names = VIRTUAL_BUTTON_NAMES
        axis_names = VIRTUAL_AXIS_NAMES
        mode_label = "VIRTUAL (bridge output)"
    else:
        button_names = SCUF_BUTTON_NAMES
        axis_names = SCUF_AXIS_NAMES
        mode_label = "RAW (physical device)"

    is_raw_mode = virtual_dev is None

    print("=" * 60)
    print(f"Mode: {mode_label}")
    print("Press buttons and move sticks to see events.")
    if is_raw_mode:
        print("NOTE: Paddles, SAX, G-keys, and Profile button are read from HID raw")
        print("by the driver and will NOT appear here (evdev does not expose them).")
        print(f"{RED}[ERROR]{RESET} markers indicate axis codes remapped by the driver.")
    print("Press Ctrl+C to exit.")
    print("=" * 60)
    print()

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_SYN:
                continue

            if event.type == ecodes.EV_KEY:
                name = button_names.get(event.code, f"UNKNOWN (0x{event.code:03x})")
                state = "PRESSED" if event.value == 1 else "RELEASED" if event.value == 0 else f"value={event.value}"
                if is_raw_mode and event.code in RAW_WRONG_BUTTONS:
                    print(f"{RED}[ERROR] BUTTON: {name:45s} {state}{RESET}")
                else:
                    print(f"BUTTON: {name:45s} {state}")

            elif event.type == ecodes.EV_ABS:
                name = axis_names.get(event.code, f"UNKNOWN (0x{event.code:02x})")
                if is_raw_mode and event.code in RAW_WRONG_AXES:
                    print(f"{RED}[ERROR] AXIS:   {name:45s} value={event.value}{RESET}")
                else:
                    print(f"AXIS:   {name:45s} value={event.value}")

            else:
                print(f"OTHER:  type={event.type} code={event.code} value={event.value}")

    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        dev.close()


if __name__ == "__main__":
    main()
