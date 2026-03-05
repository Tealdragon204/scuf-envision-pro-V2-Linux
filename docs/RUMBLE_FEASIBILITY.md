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

### Step 1: HID Descriptor Analysis (Linux — Try This First)

The HID report descriptor is a chunk of data baked into the controller's firmware that describes every type of data the controller can send AND receive. If it lists an **Output report**, that tells us the exact format for sending rumble commands. This can potentially solve the whole mystery without needing Windows at all.

#### Part A: Find Your SCUF's hidraw Device

1. Plug in your SCUF controller via USB
2. Open a terminal
3. Run this to list all hidraw devices and find the SCUF:
   ```bash
   ls /sys/class/hidraw/
   ```
   You'll see something like: `hidraw0  hidraw1  hidraw2  hidraw3`

4. Check each one to find which belongs to the SCUF:
   ```bash
   cat /sys/class/hidraw/hidraw0/device/uevent
   cat /sys/class/hidraw/hidraw1/device/uevent
   cat /sys/class/hidraw/hidraw2/device/uevent
   cat /sys/class/hidraw/hidraw3/device/uevent
   ```
   Look for the one that has `1B1C` (Corsair/SCUF vendor ID) in the `HID_ID` line. It'll look like:
   ```
   HID_ID=0003:00001B1C:00003A05
   ```
   The `3A05` means wired, `3A08` means wireless receiver. Note the hidraw number (e.g., `hidraw2`).

5. If your SCUF matches multiple hidraw devices (it probably will — the controller has multiple USB interfaces), that's normal. The gamepad interface is the one we care about. The driver's discovery code identifies it as **Interface 3 (if03)**. You can check:
   ```bash
   ls -la /sys/class/hidraw/hidraw2/device/
   ```
   Look at where the symlink points — if the path contains `if03`, that's the gamepad interface.

#### Part B: Dump the Raw HID Report Descriptor

1. Run this command (replace `hidraw2` with your number from Part A):
   ```bash
   xxd /sys/class/hidraw/hidraw2/device/report_descriptor
   ```
   This prints the raw bytes of the descriptor. It'll look like gibberish hex:
   ```
   00000000: 0501 0905 a101 0509 1901 2910 1500 2501  ..).....)...%.
   00000010: 7508 950a 8102 0600 ff09 2015 0026 ff00  u......... ..&..
   ...
   ```
   **Copy the entire output** — we'll need it.

2. For a more human-readable version, install `usbhid-dump`:
   ```bash
   # On Ubuntu/Debian:
   sudo apt install usbutils

   # On Arch/Garuda:
   sudo pacman -S usbutils
   ```
   Then run:
   ```bash
   sudo usbhid-dump -d 1b1c:3a05 -e descriptor
   ```
   This gives a cleaner hex dump grouped by interface.

#### Part C: Parse the Descriptor Into Something Readable

The raw hex is hard to read by hand. Let's convert it to a human-readable format.

**Option 1: Use an online parser (easiest)**
1. Copy the hex bytes from Part B (just the hex values, no addresses or ASCII)
2. Go to https://eleccelerator.com/usbdescreqparser/
3. Paste the hex into the "USB Descriptor" field
4. It will decode it into readable lines like:
   ```
   Usage Page (Generic Desktop)
   Usage (Gamepad)
   Collection (Application)
     Report ID (1)
     Usage Page (Button)
     ...
     Report ID (3)            <-- OUTPUT REPORT ID
     Usage Page (Vendor Defined)
     Report Count (8)
     Report Size (8)
     Output (Data, Variable, Absolute)
   ```

**Option 2: Use hidrd-convert (command line)**
   ```bash
   # Install on Ubuntu/Debian:
   sudo apt install hidrd

   # Install on Arch/Garuda:
   yay -S hidrd   # (from AUR)

   # Then parse:
   xxd -r -p /sys/class/hidraw/hidraw2/device/report_descriptor | hidrd-convert -o spec
   ```
   (The `xxd -r -p` part is not needed if you pipe from usbhid-dump — use the method that works for you.)

**Option 3: Use hid-tools (Python-based, very readable output)**
   ```bash
   sudo pip install hid-tools
   sudo hid-decode /dev/hidraw2
   ```

#### Part D: What to Look For in the Parsed Descriptor

Once you have the human-readable output, search for these things:

1. **"Output" reports**: Lines containing the word `Output`. These define data the computer sends TO the controller. Rumble commands will be in an Output report.
   - If you see `Output (Data, Variable, Absolute)` — this is exactly what we want
   - Note the **Report ID** above it (a number like `0x03` or `0x05`)
   - Note the **Report Count** and **Report Size** — these tell you how many bytes the report is
     - Example: `Report Count (8)` + `Report Size (8)` = 8 bytes of data

2. **Usage Page (Physical Interface Device)** or **Usage Page (0x0F)**: This is the official HID way to describe force feedback. If you see this, the controller has a formal rumble descriptor.

3. **Usage Page (Vendor Defined)** or **Usage Page (0xFF00)**: This means the manufacturer (Corsair/SCUF) defined a custom format. Less self-documenting, but the byte sizes still tell us the report structure.

4. **No Output reports at all**: If the descriptor only has Input reports, the controller might use a different HID interface for rumble, or it might use a different USB mechanism entirely. In this case, the Windows capture becomes essential.

#### Part E: Example of What Success Looks Like

If the descriptor reveals rumble, you might see something like this:

```
Report ID (3)                       <-- rumble report uses ID 0x03
Usage Page (Vendor Defined)
Usage (Vendor Usage 1)
Logical Minimum (0)
Logical Maximum (255)               <-- motor values are 0-255
Report Size (8)                     <-- each value is 1 byte
Report Count (6)                    <-- 6 bytes of data after the report ID
Output (Data, Variable, Absolute)   <-- this is an OUTPUT report = host-to-device
```

This would tell us: send 7 bytes total (`[0x03, byte1, byte2, byte3, byte4, byte5, byte6]`) where the report ID is `0x03` and we need the Windows capture (or trial and error) to figure out which of the 6 data bytes control which motor.

#### Part F: What to Share Back

Please share:
1. The full output of `xxd /sys/class/hidraw/hidrawN/device/report_descriptor` (for all SCUF hidraw devices you found)
2. The parsed/decoded version if you got one from the online tool or hidrd-convert
3. Which hidraw number matched which interface (if you checked)

Even if the descriptor doesn't obviously show rumble, the raw dump is still valuable — I can analyze it to determine the full report structure.

#### Troubleshooting

- **"Permission denied" on hidraw**: Use `sudo` for the commands, or make sure the udev rules from the driver are installed (`sudo cp 99-scuf-envision.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger`)
- **"No such file" for report_descriptor**: Make sure the controller is plugged in and detected (`lsusb | grep 1b1c` should show something)
- **"hidrd-convert not found"**: Use the online parser instead — it does the same thing
- **"hid-decode shows nothing useful"**: Try the raw `xxd` dump + online parser approach instead
- **Multiple hidraw devices for the SCUF**: This is normal — the controller has multiple interfaces. Dump all of them. The gamepad one (Interface 3) is the most likely to have rumble, but it could be on another interface

### Step 2: USB Packet Capture on Windows (Recommended)

This is the most reliable way to figure out what bytes Windows sends to make the controller vibrate. We'll use Wireshark (free) to "sniff" the USB traffic.

#### Part A: Install Wireshark + USBPcap

1. Go to https://www.wireshark.org/download.html
2. Download the **Windows x64 Installer**
3. Run the installer
4. **IMPORTANT**: During installation, you'll see a list of optional components. Make sure the checkbox for **USBPcap** is checked. This is what lets Wireshark see USB traffic. If you miss this, you'll need to reinstall.
5. Finish the installation and reboot if prompted

#### Part B: Plug In Your SCUF Controller

1. Connect your SCUF Envision Pro V2 via USB cable (wired is simpler for capture)
2. Open **Device Manager** (right-click Start button → Device Manager)
3. Look under **Human Interface Devices** — you should see entries for your SCUF
4. Note which USB port/hub it's on (you'll need this in the next step)

#### Part C: Start Capturing USB Traffic

1. Open **Wireshark** (run as Administrator — right-click → Run as administrator)
2. On the main screen, you'll see a list of capture interfaces. Look for one that says **USBPcap1** (or USBPcap2, USBPcap3, etc.)
   - If you don't see any USBPcap interfaces, USBPcap didn't install correctly — go back to Part A
   - If you see multiple USBPcap interfaces, you may need to try each one to find which USB bus your controller is on
3. **Double-click** on the USBPcap interface to start capturing
4. You'll immediately see a flood of USB packets scrolling by — this is normal, it's all the USB traffic on that bus

#### Part D: Filter to Only Show SCUF Traffic

The capture will be noisy (keyboard, mouse, everything on that USB bus). Let's filter it down.

1. In the **display filter bar** at the top (it says "Apply a display filter"), type:
   ```
   usb.idVendor == 0x1b1c
   ```
   and press Enter
2. If you see packets appearing, you've found the right USB bus. If nothing shows up, try the other USBPcap interfaces (go back to Part C step 2)
3. Now refine the filter to show only **outgoing** data (computer → controller). This is where rumble commands will be:
   ```
   usb.idVendor == 0x1b1c && usb.endpoint_address.direction == OUT
   ```

#### Part E: Trigger Rumble

Now we need to make the controller vibrate so we can see what bytes Windows sends.

**Option 1: Use a web-based gamepad tester (easiest)**
1. Open Chrome or Edge
2. Go to https://hardwaretester.com/gamepad
3. Press a button on your SCUF so it's detected
4. Look for a "Vibration" or "Rumble Test" section on the page
5. Click it to trigger vibration — you should feel the controller vibrate AND see new packets appear in Wireshark

**Option 2: Use the Xbox Accessories app**
1. Open the Microsoft Store, search for **Xbox Accessories**, install it
2. Open Xbox Accessories — it should detect your SCUF
3. The app may have a vibration test option

**Option 3: Use a game**
1. Open any game that has strong rumble (racing games, shooters)
2. Do something in-game that triggers vibration (crash, shoot, get hit)
3. Watch Wireshark for new packets when you feel the vibration

#### Part F: Identify the Rumble Bytes

This is the key part. When rumble triggers, you'll see new packets appear in Wireshark.

1. **Click on a packet** that appeared when rumble started
2. In the bottom pane, you'll see the raw bytes (hex dump). Look at the **"Leftover Capture Data"** or **"HID Data"** section — this is the actual data sent to the controller
3. **Write down or screenshot these bytes**. They'll look something like:
   ```
   03 0f 00 00 00 00 ff ff ff 00 00
   ```
4. Now **stop the rumble** (let the game/tester go idle). Look at the packet that went out when vibration stopped. The bytes will be similar but with `00` where the motor values were.
5. **Compare the two**: The bytes that changed between "rumble on" and "rumble off" are the motor strength values.

**Do these specific tests and note the bytes for each:**

| Test | What to do | Why |
|------|-----------|-----|
| Full rumble ON | Max vibration on both motors | See maximum byte values |
| Full rumble OFF | Stop all vibration | See what "zero" looks like |
| Strong motor only | If tester allows, left motor only | Identify which byte = strong motor |
| Weak motor only | If tester allows, right motor only | Identify which byte = weak motor |
| Half strength | 50% vibration if possible | Verify values scale linearly |

#### Part G: Save the Capture

1. In Wireshark, click **File → Save As**
2. Save as a `.pcapng` file somewhere you can find it
3. This file contains all the evidence we need

#### Part H: What to Share Back

Once you've done the capture, I need these things to implement rumble:

1. **The hex bytes** of a "rumble ON" packet (the Leftover Capture Data section)
2. **The hex bytes** of a "rumble OFF" packet
3. **How many bytes** the report is (count them)
4. If you could test strong-only vs weak-only, which byte positions changed
5. (Optional) The `.pcapng` file itself if you want me to analyze it

#### Troubleshooting

- **"I don't see any USBPcap interfaces"**: Reinstall Wireshark and make sure USBPcap checkbox is ticked during install. Reboot after.
- **"I see packets but the filter shows nothing"**: Your controller might be on a different USB bus. Try each USBPcap interface.
- **"The gamepad tester doesn't detect my controller"**: Make sure no other software (iCUE, Steam) has exclusive access. Close those programs first.
- **"Rumble works in games but I can't see different packets"**: The packets might be very small. Remove the direction filter temporarily (`usb.idVendor == 0x1b1c`) and look at all traffic. The rumble packets will be the ones that appear in sync with vibration.
- **"I see too many packets and can't tell which is rumble"**: Use the time column. Note the exact time you triggered rumble, then scroll to those timestamps. The new OUT packets at that timestamp are your rumble commands.

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
