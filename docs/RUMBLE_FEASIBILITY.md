# SCUF Envision Pro V2 — Rumble Protocol Reference

## Status: IMPLEMENTED

Rumble / force-feedback is fully integrated into the driver.
See the **Rumble / Force Feedback** section in the main README for usage instructions.

---

## HID Rumble Protocol

The rumble command is a **13-byte HID output report** written to the controller's
hidraw device (USB interface 3, the gamepad interface):

```
Offset: 0     1     2     3     4     5     6     7     8     9     10    11    12
Bytes:  0x09  0x00  0x6a  0x09  0x00  0x03  0x00  0x00  LEFT  RIGHT 0x10  0x00  0xeb
```

- **Byte 8 (LEFT)**: Left / strong motor intensity, `0x00`–`0xFF`
- **Byte 9 (RIGHT)**: Right / weak motor intensity, `0x00`–`0xFF`
- All other bytes are fixed framing.

### Sources

1. **OpenLinkHub** (Go, GPL-3.0): `src/devices/scufenvisionproV2WU/scufenvisionproV2WU.go`
   — `TriggerHapticEngineExternal()` writes the same 13-byte report via `analogListener.Write(buf)`.
   Repository: https://github.com/jurkovic-nikola/OpenLinkHub

2. **Wireshark USB capture** (user-provided, Windows wireless dongle):
   HID Data bytes end with `09 00 6a 09 00 03 00 00 ... 10 00 eb`, matching
   the OpenLinkHub packet exactly.

---

## Architecture

```
Game sends FF_RUMBLE effect
        |
        v
Virtual gamepad (uinput, EV_FF capability)
        |
        v
bridge.py polls uinput fd, receives EV_UINPUT / EV_FF events
        |
        v
rumble.py (RumbleHandler) builds 13-byte packet
        |
        v
os.write() to /dev/hidrawN
        |
        v
Physical SCUF motors vibrate
```

### Key files

| File | Role |
|------|------|
| `scuf_envision/rumble.py` | `RumbleHandler` — opens hidraw, scales FF magnitudes (0–65535 → 0–255), writes packets |
| `scuf_envision/virtual_gamepad.py` | Registers `EV_FF` / `FF_RUMBLE` capability, exposes uinput fd |
| `scuf_envision/bridge.py` | Polls uinput fd for FF upload/erase/play events, dispatches to `RumbleHandler` |
| `scuf_envision/constants.py` | `RUMBLE_REPORT` template, motor byte offsets, `FF_MAX_EFFECTS` |
| `scuf_envision/config.py` | `is_rumble_disabled()` — reads `[rumble] disabled` from config |

### Configuration

`/etc/scuf-envision/config.ini`:
```ini
[rumble]
disabled = false   # set to true to disable force-feedback entirely
```

When disabled, the virtual gamepad doesn't advertise `EV_FF`, so games never send rumble events.

---

## Quick Manual Test (Without the Driver)

If you want to test the rumble packet directly against a bare controller:

```python
import os, time
# Replace hidrawN with your SCUF's hidraw device (interface 3)
fd = os.open("/dev/hidrawN", os.O_WRONLY)

# Both motors full blast
os.write(fd, bytes([0x09,0x00,0x6a,0x09,0x00,0x03,0x00,0x00, 0xFF,0xFF, 0x10,0x00,0xeb]))
time.sleep(1)

# Stop
os.write(fd, bytes([0x09,0x00,0x6a,0x09,0x00,0x03,0x00,0x00, 0x00,0x00, 0x10,0x00,0xeb]))
os.close(fd)
```
