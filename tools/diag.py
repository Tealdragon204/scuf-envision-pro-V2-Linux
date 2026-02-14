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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evdev
from evdev import ecodes, categorize
from scuf_envision.discovery import discover_scuf
from scuf_envision.constants import BUTTON_MAP, AXIS_MAP

# Human-readable names for the SCUF's actual physical buttons
SCUF_BUTTON_NAMES = {
    ecodes.BTN_SOUTH: "A (BTN_SOUTH)",
    ecodes.BTN_EAST:  "B (BTN_EAST)",
    ecodes.BTN_C:     "X (BTN_C) -> should be BTN_WEST",
    ecodes.BTN_NORTH: "Y (BTN_NORTH)",
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
}


def main():
    print("=" * 60)
    print("SCUF Envision Pro V2 - Diagnostic Tool")
    print("=" * 60)
    print()

    discovered = discover_scuf()
    if discovered is None:
        print("ERROR: No SCUF controller found!")
        print("  - Is the controller plugged in via USB?")
        print("  - Check: lsusb | grep 1b1c")
        sys.exit(1)

    print(f"Primary device:    {discovered.event_path}")
    print(f"HID raw device:    {discovered.hidraw_path or 'not found'}")
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
