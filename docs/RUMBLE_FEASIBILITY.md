# SCUF Envision Pro V2 — Rumble Feature Feasibility Research

## Context

The SCUF Envision Pro V2 Linux driver is a Python userspace bridge (`python-evdev` + `uinput`) that remaps the controller's non-standard HID inputs to Xbox-standard codes. It currently handles buttons, sticks, triggers, d-pad, and USB audio — but has **no rumble/force feedback support**. This document assesses feasibility and outlines the path to implementation.

---

## Feasibility Verdict: Yes, Rumble Is Possible

| Component | Feasible? | Confidence | Notes |
|-----------|-----------|------------|-------|
| Linux FF framework (software) | Yes | High | `python-evdev` UInput supports `EV_FF`/`FF_RUMBLE` natively |
| Virtual gamepad FF registration | Yes | High | Just add `EV_FF` capability to existing UInput creation |
| Receiving FF events from games | Yes | High | Poll UInput fd alongside physical device fd |
| Sending commands to hardware | Yes | High | `hidraw` path already discovered, just need to `open()` + `write()` |
| **HID rumble protocol** | **Unknown** | **Medium** | Requires reverse engineering — the only real blocker |
| Enable/disable toggle | Yes | High | Mirrors existing audio config pattern exactly |

**Bottom line**: The entire software pipeline exists and is proven. The single unknown is what bytes to write to the SCUF's hidraw device to control the rumble motors.

---

## Current Architecture (Relevant to Rumble)

### What exists today
- **Physical device** → evdev (`/dev/input/eventN`) — read-only, exclusively grabbed
- **Virtual gamepad** → uinput (`/dev/input/eventM`) — write-only (buttons + axes)
- **hidraw** → `/dev/hidrawN` — discovered in `discovery.py:264-323`, stored in `DiscoveredDevice.hidraw_path`, **but never opened or written to**
- **Config system** → `/etc/scuf-envision/config.ini` with `[audio] disabled` toggle

### What's missing for rumble
1. `EV_FF` + `FF_RUMBLE` capability on the virtual gamepad (so games know FF is available)
2. Polling the virtual gamepad's fd for incoming FF events from games
3. A handler to translate FF effects → HID output reports
4. Writing those reports to hidraw
5. A `[rumble] disabled` config toggle

### Event flow (once implemented)
```
Game → FF_RUMBLE effect → Virtual gamepad (uinput fd)
  → bridge.py receives EV_FF / EV_UINPUT event
  → RumbleHandler translates to HID output report bytes
  → write() to /dev/hidrawN
  → Physical SCUF motors vibrate
```

---

## The Unknown: HID Rumble Protocol

### What we know
- VID: `0x1B1C` (Corsair), PID: `0x3A05` (wired) / `0x3A08` (wireless)
- The controller is Xbox-licensed by SCUF/Corsair
- Rumble works on Windows (confirmed by user) — so the hardware supports it
- The controller uses HID over USB with multiple interfaces (gamepad = interface 3)
- hidraw device is already located by the driver

### What we don't know
- The HID output report ID for rumble commands
- The byte layout (which offsets control strong motor, weak motor, trigger motors)
- The value range (0-255? 0-100? 0-65535?)
- Whether it uses standard HID output reports or vendor-specific feature reports
- Whether the wired and wireless protocols differ

### Likely protocol candidates

Since the SCUF Envision Pro is Xbox-licensed, these are the most probable formats:

**Candidate 1: Xbox One / GIP-like format**
```
Report ID 0x03:
[0x03, 0x0F, 0x00, 0x00, left_trigger, right_trigger, strong_motor, weak_motor, 0xFF, 0x00, 0x00]
```
- Used by Xbox One controllers and many Xbox-compatible gamepads
- Motor values: 0-255

**Candidate 2: XInput-style simplified**
```
Report ID 0x00 or 0x01:
[report_id, 0x08, 0x00, strong_motor, weak_motor, 0x00, 0x00, 0x00]
```
- Used by some third-party Xbox controllers

**Candidate 3: Corsair/iCUE proprietary**
```
Vendor-specific report with Corsair protocol framing
```
- Corsair devices often use proprietary protocols for their iCUE software
- Less likely for gamepad rumble (usually reserved for RGB/config)

---

## Reverse Engineering Strategy

### Step 1: HID Descriptor Analysis (Linux, no Windows needed)

Run on Linux with the controller plugged in:

```bash
# Dump raw HID report descriptor
cat /sys/class/hidraw/hidrawN/device/report_descriptor | xxd

# Or with usbhid-dump (more readable)
sudo usbhid-dump -d 1b1c:3a05 -e descriptor

# Parse with hidrd-convert if available
sudo usbhid-dump -d 1b1c:3a05 -e descriptor | hidrd-convert -o spec
```

**What to look for**:
- `Output` report definitions (these are host→device, i.e., rumble commands)
- Report IDs associated with output reports
- Usage Page `0x0F` (Physical Interface Device / Force Feedback) or generic vendor-defined
- Field sizes and counts in output reports

This alone may reveal the protocol without needing Windows.

### Step 2: USB Packet Capture on Windows (Recommended)

**Tools needed**:
- Wireshark + USBPcap (free): https://wiki.wireshark.org/CaptureSetup/USB
- OR: USBlyzer (commercial, easier UI)

**Procedure**:
1. Install Wireshark with USBPcap on Windows
2. Start capture on the USB bus where the SCUF is connected
3. Open a game or use **XInput Test** / **Gamepad Tester** / **x360ce** to trigger rumble
4. Filter capture: `usb.idVendor == 0x1b1c && usb.transfer_type == URB_INTERRUPT` (output direction)
5. Look for **SET_REPORT** or **interrupt OUT** transfers
6. Vary rumble intensity (low, medium, max) and note byte changes
7. Test strong motor only, weak motor only, both, triggers (if applicable)
8. Export the relevant packets

**What to capture**:
- Minimum 3 samples: rumble off (0,0), strong motor max (255,0), weak motor max (0,255)
- Ideally also: mixed values, gradual ramp up/down, trigger rumble if supported

### Step 3: Validate on Linux

Once candidate bytes are identified:

```python
# Quick test script
import os
hidraw = os.open("/dev/hidrawN", os.O_WRONLY)
# Try the captured byte sequence:
os.write(hidraw, bytes([0x03, 0x0F, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0x00]))
# If motors spin, protocol confirmed!
# Send zeros to stop:
os.write(hidraw, bytes([0x03, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00]))
os.close(hidraw)
```

---

## Implementation Roadmap (For When We're Ready to Code)

### Files to modify
| File | Change |
|------|--------|
| `scuf_envision/constants.py` | Add `FF_MAX_EFFECTS`, rumble report template |
| `scuf_envision/config.py` | Add `[rumble]` defaults, `is_rumble_disabled()`, `set_rumble_disabled()` |
| `scuf_envision/virtual_gamepad.py` | Register `EV_FF`/`FF_RUMBLE` capability, expose UInput fd |
| `scuf_envision/bridge.py` | Poll UInput fd, handle `EV_FF`/`EV_UINPUT` events, wire up rumble handler |
| `config.ini.default` | Add `[rumble] disabled = false` |

### New files
| File | Purpose |
|------|---------|
| `scuf_envision/rumble.py` | `RumbleHandler` class: opens hidraw, translates FF effects to HID writes |
| `tools/rumble_test.py` | Diagnostic tool: dump HID descriptors, test byte sequences manually |

### Implementation complexity estimate
- Config toggle: ~20 lines across `config.py` + `config.ini.default`
- Virtual gamepad FF registration: ~15 lines in `virtual_gamepad.py`
- Bridge FF event handling: ~40 lines in `bridge.py`
- RumbleHandler: ~80 lines in `rumble.py` (once protocol is known)
- Diagnostic tool: ~100 lines in `tools/rumble_test.py`
- **Total: ~255 lines of new code**

### python-evdev FF API summary
```python
# Registration (in virtual_gamepad.py):
capabilities[ecodes.EV_FF] = [ecodes.FF_RUMBLE]
uinput = UInput(events=capabilities, ..., ff_effects_max=16)

# Receiving (in bridge.py - poll the UInput fd):
# When game uploads effect: uinput.begin_upload() → get effect → uinput.end_upload()
# When game plays effect: EV_FF event, code=effect_id, value=iterations
# When game stops effect: EV_FF event, code=effect_id, value=0
# When game erases effect: uinput.begin_erase() → get id → uinput.end_erase()
```

---

## Enable/Disable Design

Mirrors the existing audio toggle pattern:

- **Config**: `[rumble] disabled = false` in `/etc/scuf-envision/config.ini`
- **When disabled**: Virtual gamepad doesn't register `EV_FF` → games see no FF support → never send rumble
- **When enabled**: Full FF pipeline active
- **Default**: Enabled (most users want rumble)
- **Future CLI**: `scuf-rumble-toggle {status|enable|disable}` (same pattern as `scuf-audio-toggle`)

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| HID protocol is vendor-proprietary and undocumented | Can't send rumble commands | USB capture on Windows will definitively reveal it |
| Wired vs wireless use different protocols | Need two code paths | Test both; likely same report format over different transport |
| hidraw write permissions | Permission denied at runtime | Already handled — udev rules (`99-scuf-envision.rules`) grant hidraw access |
| Incorrect byte sequence crashes/bricks controller | Hardware damage | HID output reports are safe — worst case is no response or garbled rumble |
| python-evdev FF API limitations | Can't receive effects properly | Well-tested API, used by other Python gamepad drivers (e.g., ds4drv, dualsense-linux) |

---

## Recommended Next Steps

1. **Now**: Dump the HID report descriptor on Linux (`usbhid-dump` or sysfs) — this is zero-risk and may reveal the protocol immediately
2. **Soon**: Do the Windows USB capture with Wireshark + USBPcap while triggering rumble
3. **Then**: Validate the discovered protocol with a quick Python hidraw write test on Linux
4. **Finally**: Implement the full integration (estimated ~255 lines of code)
