"""
Hardware constants and input mapping tables for the SCUF Envision Pro V2.

All input is read from raw HID interfaces, bypassing the kernel HID→evdev
translation layer entirely:
  - Digital buttons + DPAD: 32-bit bitmask packets (data[2]==0x02) on the
    control HID interface — same path as battery and RGB commands.
  - Analog sticks: int16 LE pairs on USB interface 3 (the dedicated analog
    endpoint), matching OLH's analogDataListener.
  - Triggers: uint16 LE pairs in trigger packets (data[2]==0x0a) on the
    control HID interface.

Source for HID packet layout: OpenLinkHub (Go) scufenvisionproV2W.go
"""

import evdev
from evdev import ecodes

# --- USB IDs ---
SCUF_VENDOR_ID = 0x1B1C
SCUF_PRODUCT_ID_WIRED = 0x3A05
SCUF_PRODUCT_ID_RECEIVER = 0x3A08

# --- HID button packet ---
# Button data arrives in packets where data[0]==0x03 and data[2]==0x02.
# The 32-bit little-endian button mask starts at byte offset 3.
HID_BTN_MASK_OFFSET = 3

# 32-bit bitmask → canonical virtual button code (emitted to uinput).
# DPAD bits are excluded here; they are converted to HAT axes via HID_DPAD.
HID_BUTTON_MAP: dict[int, int] = {
    0x000020: ecodes.BTN_SOUTH,             # A
    0x000040: ecodes.BTN_NORTH,             # X
    0x000080: ecodes.BTN_WEST,              # Y
    0x000100: ecodes.BTN_EAST,              # B
    0x000200: ecodes.BTN_TL,                # LB
    0x000400: ecodes.BTN_TR,                # RB
    0x002000: ecodes.BTN_THUMBL,            # L3
    0x004000: ecodes.BTN_THUMBR,            # R3
    0x010000: ecodes.BTN_SELECT,            # Back/Select
    0x020000: ecodes.BTN_START,             # Start/Menu
    0x040000: ecodes.BTN_TRIGGER_HAPPY1,    # P1 (rear, bottom-left)
    0x080000: ecodes.BTN_TRIGGER_HAPPY2,    # P2 (rear, bottom-right)
    0x100000: ecodes.BTN_TRIGGER_HAPPY3,    # P3 (rear, top-left)
    0x200000: ecodes.BTN_TRIGGER_HAPPY4,    # P4 (rear, top-right)
    0x400000: ecodes.BTN_TRIGGER_HAPPY5,    # S1 (SAX left grip)
    0x800000: ecodes.BTN_TRIGGER_HAPPY6,    # S2 (SAX right grip)
    0x1000000: ecodes.BTN_MODE,             # Home/Power/Xbox
    0x4000000: ecodes.BTN_TRIGGER_HAPPY7,   # G1
    0x8000000: ecodes.BTN_TRIGGER_HAPPY8,   # G2
    0x10000000: ecodes.BTN_TRIGGER_HAPPY9,  # G3
    0x20000000: ecodes.BTN_TRIGGER_HAPPY10, # G4
    0x40000000: ecodes.BTN_TRIGGER_HAPPY11, # G5
    0x80000000: ecodes.BTN_TRIGGER_HAPPY12, # Profile button
}

# DPAD: (bitmask, HAT axis code, direction value).
# HAT0X: -1=Left, 0=Centre, +1=Right
# HAT0Y: -1=Up,   0=Centre, +1=Down
HID_DPAD: tuple[tuple[int, int, int], ...] = (
    (0x000002, ecodes.ABS_HAT0Y, -1),  # Up
    (0x000004, ecodes.ABS_HAT0Y, +1),  # Down
    (0x000008, ecodes.ABS_HAT0X, -1),  # Left
    (0x000010, ecodes.ABS_HAT0X, +1),  # Right
)

# Sorted button code list for uinput capability declaration.
VIRTUAL_BUTTONS: list[int] = sorted(HID_BUTTON_MAP.values())

# --- Axis ranges ---
STICK_MIN = -32768
STICK_MAX = 32767
TRIGGER_MIN = 0
TRIGGER_MAX = 1023

AXIS_INFO = {
    ecodes.ABS_X:     evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=8, flat=0, resolution=0),
    ecodes.ABS_Y:     evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=8, flat=0, resolution=0),
    ecodes.ABS_RX:    evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=8, flat=0, resolution=0),
    ecodes.ABS_RY:    evdev.AbsInfo(value=0, min=STICK_MIN, max=STICK_MAX, fuzz=8, flat=0, resolution=0),
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

# --- Rumble HID protocol ---
# 13-byte HID output report to control rumble motors.
# Confirmed via OpenLinkHub (Go) and Wireshark USB capture on Windows.
# Written to the hidraw device on USB interface 3.
RUMBLE_REPORT = bytearray([
    0x09, 0x00, 0x6a, 0x09, 0x00, 0x03, 0x00, 0x00,
    0x00,  # byte 8: left (strong) motor, 0x00-0xFF
    0x00,  # byte 9: right (weak) motor, 0x00-0xFF
    0x10, 0x00, 0xeb,
])
RUMBLE_LEFT_OFFSET = 8
RUMBLE_RIGHT_OFFSET = 9
FF_MAX_EFFECTS = 16  # max concurrent force-feedback effects

# --- Vibration module HID commands ---
# Sent via the transfer protocol to set hardware motor intensity (0-100).
# Equivalent to iCUE's vibration intensity slider on Windows.
# Protocol: 65-byte buffer with header [0x00, 0x02, 0x08, 0x01] + payload.
VIBRATION_LEFT_CMD = 0x84
VIBRATION_RIGHT_CMD = 0x85
VIBRATION_MAX_INTENSITY = 100
VIBRATION_TRANSFER_HEADER = bytearray([0x00, 0x02, 0x08, 0x01])
VIBRATION_TRANSFER_SIZE = 65

# --- RGB HID protocol ---
# Confirmed via OpenLinkHub (Go) source for SCUF Envision Pro V2.
RGB_CMD_OPEN_ENDPOINT    = bytes([0x0d, 0x00, 0x01])
RGB_CMD_WRITE_COLOR      = bytes([0x06, 0x00])
RGB_CMD_INIT_WRITE       = bytes([0x01])                  # OLH cmdInitWrite prefix
RGB_CMD_TRIGGER_BACKEND  = bytes([0xc0, 0x00, 0x01])      # activate trigger endpoint
RGB_CMD_ECO_MODE_OFF     = bytes([0x0b, 0x00, 0x00])      # disable eco mode (enables LEDs)
RGB_NUM_LEDS             = 9   # 9 channels; layout: R[0-8] G[9-17] B[18-26]
RGB_FRAME_SIZE           = 27  # 3 planes × 9 LEDs

# --- Polling ---
POLL_TIMEOUT_MS = 2  # 500 Hz — matches hardware report rate (wired + Slipstream wireless)

# --- Analog deadzone HID command bytes (UNVERIFIED — do not use until confirmed) ---
# These byte sequences were inferred from OLH RGB init patterns, NOT confirmed via
# USB capture of OLH setting deadzone values. Sending wrong commands mutes axis
# reporting on the physical device. Verify with Wireshark/USBmon before enabling.
# Three-step protocol per device: init → write min DZ value → write max DZ value.
# Values 0–15; combined with RGB_CMD_INIT_WRITE prefix via _packet() in hid.py.
_DZ_INIT = [bytes([0x80, 0x00]), bytes([0x81, 0x00]), bytes([0x7e, 0x00]), bytes([0x7f, 0x00])]
_DZ_MIN  = [bytes([0x7c, 0x00]), bytes([0x7d, 0x00]), bytes([0x7a, 0x00]), bytes([0x7b, 0x00])]
_DZ_MAX  = [bytes([0xdd, 0x00]), bytes([0xde, 0x00]), bytes([0xdb, 0x00]), bytes([0xdc, 0x00])]
# Index order: 0=left stick, 1=right stick, 2=left trigger, 3=right trigger

# --- Deadzone defaults (Hall Effect conservative) ---
STICK_DEADZONE = 200           # ~0.6% radial — handles gravity/hand-shake only
TRIGGER_DEADZONE = 5           # Minimal trigger floor
STICK_JITTER_THRESHOLD = 32    # Hall Effect: much less noisy than potentiometers
