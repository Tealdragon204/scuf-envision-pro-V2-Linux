"""
Hardware constants and input mapping tables for the SCUF Envision Pro V2.

The SCUF Envision Pro V2 reports wildly non-standard evdev button and axis
codes. This module defines the translation tables from the physical device's
codes to standard Xbox gamepad codes.

Sources:
  - Scufpad (C#): https://github.com/ChaseDRedmon/Scufpad
  - Gicotto/cacique: https://github.com/Gicotto/cacique-envision-pro-linux
  - Hardware testing on Garuda Linux
"""

import evdev
from evdev import ecodes

# --- USB IDs ---
SCUF_VENDOR_ID = 0x1B1C      # Corsair (parent company of SCUF)
SCUF_PRODUCT_ID_WIRED = 0x3A05   # SCUF Envision Pro Controller V2 (wired)
SCUF_PRODUCT_ID_RECEIVER = 0x3A09  # SCUF Envision Pro Wireless USB Receiver V2

# --- Button mapping ---
# The SCUF sends non-standard evdev button codes.
# Map: physical_code -> (standard Xbox code, human name)
#
# Physical layout reference (SCUF face buttons use Xbox ABXY layout):
#   Y (top), X (left), B (right), A (bottom)

BUTTON_MAP = {
    ecodes.BTN_SOUTH:          ecodes.BTN_SOUTH,          # A -> A
    ecodes.BTN_EAST:           ecodes.BTN_EAST,           # B -> B
    ecodes.BTN_C:              ecodes.BTN_NORTH,          # SCUF sends BTN_C for X -> BTN_NORTH (kernel: BTN_X=BTN_NORTH)
    ecodes.BTN_NORTH:          ecodes.BTN_WEST,           # Y -> BTN_WEST (kernel: BTN_Y=BTN_WEST)
    ecodes.BTN_WEST:           ecodes.BTN_TL,             # SCUF sends BTN_WEST for LB
    ecodes.BTN_Z:              ecodes.BTN_TR,             # SCUF sends BTN_Z for RB
    ecodes.BTN_TL:             ecodes.BTN_SELECT,         # SCUF sends BTN_TL for Select/Back
    ecodes.BTN_TR:             ecodes.BTN_START,          # SCUF sends BTN_TR for Start/Menu
    ecodes.BTN_TL2:            ecodes.BTN_THUMBL,         # SCUF sends BTN_TL2 for L3
    ecodes.BTN_TR2:            ecodes.BTN_THUMBR,         # SCUF sends BTN_TR2 for R3
    ecodes.BTN_MODE:           ecodes.BTN_MODE,           # Guide/Xbox button (correct)
}

# Paddle buttons (V2 has 3 physical paddles, maps to Xbox Elite paddle slots)
PADDLE_MAP = {
    ecodes.BTN_TRIGGER_HAPPY1: ecodes.BTN_TRIGGER_HAPPY1,  # Paddle 1
    ecodes.BTN_TRIGGER_HAPPY2: ecodes.BTN_TRIGGER_HAPPY2,  # Paddle 2
    ecodes.BTN_TRIGGER_HAPPY3: ecodes.BTN_TRIGGER_HAPPY3,  # Paddle 3
}

# --- Axis mapping ---
# The SCUF also sends axes on wrong codes.
# Map: physical_axis_code -> standard Xbox axis code

AXIS_MAP = {
    ecodes.ABS_X:      ecodes.ABS_X,      # Left Stick X (correct)
    ecodes.ABS_Y:      ecodes.ABS_Y,      # Left Stick Y (correct)
    ecodes.ABS_Z:      ecodes.ABS_RX,     # SCUF sends ABS_Z for Right Stick X
    ecodes.ABS_RX:     ecodes.ABS_Z,      # SCUF sends ABS_RX for Left Trigger
    ecodes.ABS_RY:     ecodes.ABS_RZ,     # SCUF sends ABS_RY for Right Trigger
    ecodes.ABS_RZ:     ecodes.ABS_RY,     # SCUF sends ABS_RZ for Right Stick Y
    ecodes.ABS_HAT0X:  ecodes.ABS_HAT0X,  # D-pad X (correct)
    ecodes.ABS_HAT0Y:  ecodes.ABS_HAT0Y,  # D-pad Y (correct)
}

# --- Axis ranges ---
# (min, max, fuzz, flat) for each output axis on the virtual device
STICK_MIN = -32768
STICK_MAX = 32767
TRIGGER_MIN = 0
TRIGGER_MAX = 1023

AXIS_INFO = {
    ecodes.ABS_X:     evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=16, flat=128, resolution=0),
    ecodes.ABS_Y:     evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=16, flat=128, resolution=0),
    ecodes.ABS_RX:    evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=16, flat=128, resolution=0),
    ecodes.ABS_RY:    evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=16, flat=128, resolution=0),
    ecodes.ABS_Z:     evdev.AbsInfo(value=0, min=TRIGGER_MIN, max=TRIGGER_MAX, fuzz=0, flat=0, resolution=0),
    ecodes.ABS_RZ:    evdev.AbsInfo(value=0, min=TRIGGER_MIN, max=TRIGGER_MAX, fuzz=0, flat=0, resolution=0),
    ecodes.ABS_HAT0X: evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0),
    ecodes.ABS_HAT0Y: evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0),
}

# --- Virtual device identity ---
VIRTUAL_DEVICE_NAME = "SCUF Envision Pro V2 (Xbox Mode)"
VIRTUAL_VENDOR = 0x045E   # Microsoft (so games recognize it as Xbox)
VIRTUAL_PRODUCT = 0x0B13  # Xbox Wireless Controller (matches Xbox Elite 2)
VIRTUAL_VERSION = 0x0001

# --- Polling ---
POLL_TIMEOUT_MS = 4  # ~250 Hz polling rate

# --- Deadzone defaults ---
STICK_DEADZONE = 3500          # ~10.7% radial deadzone
TRIGGER_DEADZONE = 10          # Minimal trigger deadzone
STICK_JITTER_THRESHOLD = 64    # Ignore changes smaller than this
