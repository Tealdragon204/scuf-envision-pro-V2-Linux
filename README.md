# SCUF Envision Pro V2 - Linux Driver

A userspace driver that makes the SCUF Envision Pro V2 controller work correctly on Linux with proper Xbox button mapping, RGB control, rumble, profiles, and more.

**Tested on:** Garuda Linux (Arch-based) with KDE Plasma

## Features

- **Button/axis remapping** — reads all input directly from HID raw packets and emits correct Xbox-compatible codes via uinput
- **Named profiles** — per-game button remapping, switched live with no restart
- **RGB control** — 12 animation modes (static, rainbow, breathe, colorpulse, etc.); activity-based state changes; per-profile overrides
- **Rumble / force feedback** — full FF_RUMBLE + FF_GAIN passthrough to the controller's motors
- **Deadzone & anti-deadzone** — radial SW deadzone, jitter suppression, per-profile anti-deadzone to defeat in-game deadzones in older titles
- **Response curves** — 4 presets (linear, aggressive, steady, relaxed) or fully custom 6-point piecewise curve; separate curve for sticks and triggers; per-profile override
- **System tray** — notification-area icon with live connection/battery status, one-click profile switching, and RGB shortcuts
- **Battery monitoring** — polls via HID raw interface, sends desktop notifications at configurable thresholds
- **Wireless support** — auto-reconnect loop keeps the virtual gamepad alive for up to 5 min while the controller reconnects
- **USB audio fix** — fixes broken hardware mixer and PipeWire/WirePlumber volume control
- **IPC / CLI** — `scuf-ctl` sends live commands to the running driver; `scuf-profile` wraps game launches

## How It Works

```
Physical SCUF Controller (VID 1b1c, PID 3a05 wired / 3a08 wireless)
        |
        +--- evdev interface (/dev/input/eventN)
        |         Auto-detection (sysfs VID:PID scan)
        |         Exclusive grab — suppresses kernel events to other processes
        |         Read/drain loop — disconnect detection only; input not processed
        |
        +--- HID raw — control (/dev/hidrawN, USB interface 0)
        |         Button + DPAD packets  (data[2]==0x02)
        |         Trigger L2/R2 packets  (data[2]==0x0a)
        |         Battery polling (every 60s) -> desktop notifications
        |         RGB animation engine (software, 60 fps)
        |         Rumble: FF_RUMBLE events -> HID motor packet
        |         Keepalive (every 20s, wireless)
        |
        +--- HID raw — analog (/dev/hidrawN, USB interface 3)
                  Analog stick packets (ABS_X/Y, ABS_RX/RY)

   All button, trigger, and stick events:
        |
        Profile-based remapping
        |
        Deadzone, anti-deadzone & jitter filtering
        |
        Virtual Xbox Gamepad (uinput) -> Games & Steam see a normal Xbox controller
```

---

## Installation

### Prerequisites

- Linux (Arch/Garuda, Ubuntu/Debian, or Fedora)
- Python 3.8 or newer (pre-installed on most distros)
- A USB cable for your SCUF Envision Pro V2

### Step 1: Clone the Repository

```bash
git clone https://github.com/Tealdragon204/scuf-envision-pro-V2-Linux.git
cd scuf-envision-pro-V2-Linux
```

### Step 2: Run the Installer

```bash
sudo bash install.sh
```

This does everything automatically:
- Installs dependencies: `python-evdev`, `libnotify`, `python-pyqt6`, `pillow`
- Loads the `uinput` kernel module (persists across reboots)
- Installs udev rules (device permissions + hardware mixer init on plug)
- Copies the driver to `/opt/scuf-envision`
- Installs default config to `/etc/scuf-envision/config.ini`
- Installs `scuf-audio-toggle`, `scuf-ctl`, `scuf-profile`, and `scuf-tray` tools to `/usr/local/bin/`
- Installs `scuf-tray.desktop` to `/etc/xdg/autostart/` (tray starts with your desktop session)
- Sets `SDL_GAMECONTROLLER_IGNORE_DEVICES` so Steam/SDL ignores the raw SCUF device
- Installs and starts the systemd service (auto-starts on boot)
- Installs the WirePlumber audio fix (headphone volume)

### Step 3: Reboot

```bash
sudo reboot
```

A reboot ensures the audio fix, udev rules, and systemd service all take effect cleanly.

> **You can now delete the cloned repository.** After installation, everything runs from `/opt/scuf-envision` and system directories. The repo is no longer needed.

---

## Post-Install Setup

### Verify the Controller Works

```bash
# Check the service is running
sudo systemctl status scuf-envision.service

# You should see the virtual Xbox controller listed
cat /proc/bus/input/devices | grep -A5 "SCUF Envision Pro V2 (Xbox Mode)"

# Or test with evtest (install: sudo pacman -S evtest)
sudo evtest
# Select the "SCUF Envision Pro V2 (Xbox Mode)" device
```

Press buttons and move sticks — you should see correct Xbox-mapped events.

### Steam Configuration

Steam's built-in controller support may try to read the raw SCUF device (with broken mappings) alongside our virtual Xbox controller, causing double-input or conflicting mappings.

**Option A: Environment Variable (Recommended)**

```bash
mkdir -p ~/.config/environment.d
echo 'SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05' > ~/.config/environment.d/scuf.conf
```

Log out and back in for this to take effect.

**Option B: Steam Settings**

1. Open Steam -> Settings -> Controller -> General Controller Settings
2. Find the SCUF Envision Pro entry (if listed) and disable it

---

## Configuration

All settings live in `/etc/scuf-envision/config.ini`. After editing, run:

```bash
sudo systemctl restart scuf-envision
```

Some settings (profiles, RGB) can be changed live without a restart using `scuf-ctl`.

---

### Named Profiles

Profiles let you assign different button remaps and input settings per game, switched live.

**Define a profile** in `/etc/scuf-envision/config.ini`:

```ini
# Map paddles to face buttons
[profile.BIOSHOCK]
P1 = CROSS
P2 = CIRCLE
P3 = SQUARE

# Swap Cross and Circle (Nintendo muscle memory)
[profile.NINTENDO_LAYOUT]
CROSS  = CIRCLE
CIRCLE = CROSS
```

Keys are the physical button to intercept; values are what games receive. Raw evdev names (`BTN_SOUTH`, `BTN_TL`, etc.) also work everywhere. See [HID Raw Protocol Reference](#hid-raw-protocol-reference) for the full alias list.

**Switch profiles live:**

```bash
scuf-ctl profile BIOSHOCK
scuf-ctl profile default      # restore global defaults
scuf-ctl status               # shows active profile and available profiles
```

**Auto-switch on game launch (Steam / Heroic):**

Set the game's launch option to:
```
scuf-profile BIOSHOCK %command%
```

`scuf-profile` activates the profile before the game starts and restores `default` when the game exits — including force-quit.

---

### RGB Control

#### Config file

```ini
[rgb]
mode = static          # static, off, rainbow, pastelrainbow, watercolor, rotator,
                       # colorpulse, colorshift, breathe, storm, flickering, cpu-temperature
color = 255,255,255    # primary color (R,G,B 0-255)
color2 = 0,0,255       # secondary color for two-color modes
speed = 1.0            # 0.1–20.0; higher = faster
brightness = 100       # 0–100%
```

#### Live RGB control (no restart)

```bash
scuf-ctl rgb off
scuf-ctl rgb static ff0000          # solid red
scuf-ctl rgb rainbow                # rainbow sweep
scuf-ctl rgb rainbow 3.0            # faster rainbow
scuf-ctl rgb breathe 00ff88         # breathing green
scuf-ctl rgb colorpulse ff0000 0000ff 2.0   # pulse between red and blue
scuf-ctl rgb cpu-temperature        # blue (cool) → red (hot)
```

#### Activity-based RGB

Automatically changes mode based on controller use:

```ini
[rgb]
activity_tracking = true
idle_after = 30       # seconds before idle state
sleep_after = 300     # seconds before sleep state

[rgb.active]
mode = static
color = 255,255,255
brightness = 100

[rgb.idle]
mode = static
color = 255,255,255
brightness = 20

[rgb.sleep]
mode = off
```

#### Per-profile RGB overrides

Each profile can override any RGB state:

```ini
[profile.BIOSHOCK.rgb.active]
mode = breathe
color = 255,80,0
speed = 0.8

[profile.BIOSHOCK.rgb.sleep]
mode = off
```

---

### Deadzone & Anti-Deadzone

The driver applies three layers of deadzone:

1. **Hardware deadzone** — sent to the controller firmware (currently no-op pending USB capture verification; config keys present for future use)
2. **Software radial deadzone** — circular deadzone computed from `sqrt(x²+y²)`; rescales output so the deadzone edge maps to 0 cleanly
3. **Anti-deadzone** — lifts the output floor to overcome in-game deadzones in older titles

```ini
[input]
# Software radial deadzone (0–32767). 200 is right for Hall Effect sticks.
left_stick_deadzone_sw = 200
right_stick_deadzone_sw = 200

# Anti-deadzone (0–32767). Use only for games with large internal deadzones.
# Applied to radial magnitude — direction is fully preserved.
# Typical values: 6000–10000 (20–30% of axis range).
left_stick_anti_deadzone = 0
right_stick_anti_deadzone = 0

# Trigger software deadzone (0–1023).
left_trigger_deadzone_sw = 5
right_trigger_deadzone_sw = 5

# Jitter suppression — ignore changes smaller than this (0–1000).
jitter_threshold = 32
```

**Anti-deadzone per-profile** (common pattern for older console ports):

```ini
[profile.BIOSHOCK.input]
left_stick_anti_deadzone = 9830
right_stick_anti_deadzone = 9830
```

**What anti-deadzone does:** maps the output range `[deadzone_edge, max]` → `[anti_dz, max]` linearly. The direction vector is fully preserved — only the radial magnitude gets the floor lift. At max deflection you still reach 32767. Useful values:

| Percentage | Value |
|---|---|
| 20% | 6553 |
| 30% | 9830 |
| 40% | 13107 |
| 50% | 16384 |

**Diagnose deadzone settings live:**

```bash
sudo python3 /opt/scuf-envision/tools/diag.py --deadzone
sudo python3 /opt/scuf-envision/tools/diag.py --deadzone --profile BIOSHOCK
```

Shows the active config, current deadzone values, and annotated live axis events.

---

### Response Curves

Shape the analog output of sticks and triggers with a piecewise-linear curve applied after the deadzone. Separate settings for sticks and triggers; per-profile override supported.

```ini
[input]
# Options: linear, aggressive, steady, relaxed, custom
stick_response_curve = linear
trigger_response_curve = linear
```

| Preset | Shape | Best for |
|--------|-------|----------|
| `linear` | 1:1 (default) | Neutral — identical to no curve |
| `aggressive` | ≈ √ (bows up) | Fast-paced games; quick max deflection |
| `steady` | ≈ x² (bows down) | Precision aiming; more centre control |
| `relaxed` | ≈ x³ (bows down more) | Maximum centre precision |
| `custom` | Your own 6 points | Full control |

**Custom curve** — define 6 (input%, output%) control points (same format as OpenLinkHub's `AnalogData.Points`):

```ini
[input]
stick_response_curve = custom
# 12 comma-separated values: x0,y0, x1,y1, ..., x5,y5 (percentages 0–100)
stick_curve_points = 0,0, 10,5, 30,22, 55,52, 80,82, 100,100

trigger_response_curve = custom
trigger_curve_points = 0,0, 20,20, 40,40, 60,60, 80,80, 100,100
```

**Per-profile curve override:**

```ini
[profile.BIOSHOCK.input]
stick_response_curve = steady
trigger_response_curve = linear
```

---

### Battery Monitoring

```ini
[battery]
notifications = true
notify_thresholds = 20,10,5,1
```

Low-battery desktop notifications are sent automatically at each threshold. At 1% the message reads "Controller will shut off soon!".

```bash
journalctl -u scuf-envision.service -e | grep -i battery
# Example: [INFO] scuf_envision.hid: Battery update: 47%
```

---

### Rumble / Force Feedback

Rumble is enabled by default. Supports FF_RUMBLE (separate strong/weak motors) and FF_GAIN (global intensity multiplier).

**Test rumble manually (Bash):**

```bash
for f in /sys/class/input/event*/device/name; do
  if cat "$f" 2>/dev/null | grep -q 'SCUF Envision Pro V2 (Xbox Mode)'; then
    EVENT=$(echo "$f" | grep -o 'event[0-9]*')
    sudo fftest "/dev/input/$EVENT"
    break
  fi
done
```

**Disable rumble:**

```ini
[rumble]
disabled = true
```

---

### Audio

The controller's USB audio has two problems fixed by the installer:
1. Hardware mixer defaults to 50% power — fixed via `amixer cset numid=8 32,32`
2. PipeWire/WirePlumber volume control broken — fixed via WirePlumber software volume config

**Disable SCUF audio entirely** (if you don't use the headphone jack):

```bash
sudo scuf-audio-toggle disable
sudo scuf-audio-toggle enable
sudo scuf-audio-toggle status
```

---

## CLI Tools

### scuf-ctl

IPC client for the running driver. All commands take effect immediately with no restart.

```bash
scuf-ctl ping                          # check driver is alive
scuf-ctl status                        # show profile, device, rumble/RGB state
scuf-ctl profile NAME                  # switch to named profile
scuf-ctl profile default               # restore default

scuf-ctl rgb off
scuf-ctl rgb static [RRGGBB]
scuf-ctl rgb rainbow [speed]
scuf-ctl rgb pastelrainbow [speed]
scuf-ctl rgb watercolor [speed]
scuf-ctl rgb rotator [speed]
scuf-ctl rgb breathe [RRGGBB] [speed]
scuf-ctl rgb colorpulse [RR GG] [speed]
scuf-ctl rgb colorshift [RR GG] [speed]
scuf-ctl rgb storm [RR GG]
scuf-ctl rgb flickering [RR GG] [speed]
scuf-ctl rgb cpu-temperature [speed]
scuf-ctl rgb RRGGBB                    # shorthand for static
```

`RR`/`GG` = two hex colors (e.g. `ff0000 0000ff`); `speed` = 0.1–20.0 (default 1.0).

### scuf-profile

Launch wrapper for Steam/Heroic. Activates a profile before the game and restores `default` on exit (including force-quit).

```bash
# Steam / Heroic launch option:
scuf-profile BIOSHOCK %command%

# Manual use:
scuf-profile RACING ./game
```

### scuf-tray

System tray application. Starts automatically with the desktop session after install; can also be launched manually:

```bash
scuf-tray
```

The tray icon reflects driver state:
- **Green** — controller connected (wired)
- **Teal** — controller connected (wireless)
- **Red** — driver offline or searching for controller

The menu shows connection status, battery level (when available), a profile switcher, and RGB shortcuts. The icon title includes the active profile name.

> Requires `PyQt6` and `pillow` (installed automatically by `install.sh`).

### scuf-audio-toggle

```bash
sudo scuf-audio-toggle disable    # unbind SCUF USB audio from kernel
sudo scuf-audio-toggle enable     # rebind
sudo scuf-audio-toggle status
```

---

## Diagnostics

```bash
# Live event monitor — shows SCUF raw codes → Xbox remapped codes
sudo python3 /opt/scuf-envision/tools/diag.py

# Deadzone diagnostics — shows active config + annotated axis events
sudo python3 /opt/scuf-envision/tools/diag.py --deadzone
sudo python3 /opt/scuf-envision/tools/diag.py --deadzone --profile BIOSHOCK
```

---

## Useful Commands

```bash
# Service management
sudo systemctl status scuf-envision.service
sudo systemctl restart scuf-envision.service
sudo systemctl stop scuf-envision.service

# Logs
journalctl -u scuf-envision.service -f
journalctl -u scuf-envision.service -e

# Profile management
scuf-ctl status
scuf-ctl profile BIOSHOCK
scuf-ctl profile default

# RGB
scuf-ctl rgb rainbow
scuf-ctl rgb static 00ff00
scuf-ctl rgb off
```

---

## Wireless

The driver detects the wireless receiver (`1b1c:3a08`) the same way as wired. When the controller disconnects (powered off, out of range), the virtual gamepad stays alive for up to 5 minutes while the driver waits for reconnection. Games don't see a device removal.

```bash
journalctl -u scuf-envision.service -f
# Look for: "Controller disconnected. Waiting for reconnection..."
# Then:     "Controller reconnected!"
```

---

## Updating

```bash
git pull
sudo bash install.sh
```

Then verify:

```bash
sudo systemctl status scuf-envision.service
scuf-ctl ping   # should print: pong
```

---

## Uninstallation

### Using the Uninstall Script

```bash
sudo bash /opt/scuf-envision/uninstall.sh
```

Then reboot.

### Manual / Complete Removal

```bash
# Re-enable audio if disabled
sudo scuf-audio-toggle enable 2>/dev/null; true

# Stop and remove service
sudo systemctl stop scuf-envision.service
sudo systemctl disable scuf-envision.service
sudo rm -f /etc/systemd/system/scuf-envision.service
sudo systemctl daemon-reload

# Remove CLI tools and driver files
sudo rm -f /usr/local/bin/scuf-audio-toggle /usr/local/bin/scuf-ctl /usr/local/bin/scuf-profile
sudo rm -rf /opt/scuf-envision

# Remove udev rules and audio configs
sudo rm -f /etc/udev/rules.d/99-scuf-envision.rules
sudo rm -f /etc/wireplumber/wireplumber.conf.d/50-scuf-audio.conf
sudo udevadm control --reload-rules
sudo udevadm trigger

# Remove config and uinput auto-load
sudo rm -rf /etc/scuf-envision
sudo rm -f /etc/modules-load.d/uinput.conf

# Remove SDL ignore variable
rm -f ~/.config/environment.d/scuf.conf

echo "All SCUF driver components removed."
```

Reboot after removal.

---

## Manual (Portable) Installation

> For advanced users who want to run from the cloned repo without a system-wide install.

```bash
# Arch/Garuda
sudo pacman -S python-evdev python-pyqt6 python-pillow

# Ubuntu/Debian
sudo apt install python3-evdev python3-pyqt6 python3-pil

# Fedora
sudo dnf install python3-evdev python3-pillow && pip install PyQt6

# Load uinput
sudo modprobe uinput
echo 'uinput' | sudo tee /etc/modules-load.d/uinput.conf

# Install udev rules
sudo cp 99-scuf-envision.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

# Run
sudo python3 -m scuf_envision
```

---

## HID Raw Protocol Reference

All controller input is read directly from `/dev/hidrawN` — the driver bypasses the
kernel's HID→evdev translation entirely. Two hidraw nodes are used:

- **Control hidraw** (interface 0) — buttons, DPAD, triggers, battery, RGB, keepalive
- **Analog hidraw** (interface 3) — analog stick axes

### Incoming Packet Identification

All packets from the control interface are 64 bytes. The packet type is identified
by `data[0]` and `data[2]`:

| `data[0]` | `data[2]` | Packet type | Parser |
|---|---|---|---|
| `0x03` | `0x02` | Button + DPAD bitmask | `ControlReader._parse_buttons()` |
| `0x03` | `0x0a` | Trigger axes | `ControlReader._parse_triggers()` |
| `0x03` | `0x01` (+ `data[3]==0x0f`) | Wireless battery (unsolicited) | `ControlReader._parse_battery()` |
| any | `data[3]==0x0f` | Wired battery query response | `ControlReader._parse_battery()` |
| *(analog hidraw)* | — | Analog stick axes | `AnalogListener._read_loop()` |

### Button + DPAD Packet (`data[2] == 0x02`)

`data[3:7]` is a 32-bit little-endian bitmask. Each set bit maps to one button or
DPAD direction emitted to the virtual Xbox gamepad.

| Bitmask | Physical control | Config alias | evdev output code |
|---|---|---|---|
| `0x00000001` | D-Pad Up | — | `ABS_HAT0Y = -1` |
| `0x00000002` | D-Pad Down | — | `ABS_HAT0Y = +1` |
| `0x00000004` | D-Pad Left | — | `ABS_HAT0X = -1` |
| `0x00000008` | D-Pad Right | — | `ABS_HAT0X = +1` |
| `0x00000020` | Cross / A | `CROSS` `A` | `BTN_SOUTH` |
| `0x00000040` | Square / X | `SQUARE` `X` | `BTN_NORTH` |
| `0x00000080` | Triangle / Y | `TRIANGLE` `Y` | `BTN_WEST` |
| `0x00000100` | Circle / B | `CIRCLE` `B` | `BTN_EAST` |
| `0x00000200` | L1 / LB | `L1` `LB` | `BTN_TL` |
| `0x00000400` | R1 / RB | `R1` `RB` | `BTN_TR` |
| `0x00002000` | L3 / LS (left stick click) | `L3` `LS` | `BTN_THUMBL` |
| `0x00004000` | R3 / RS (right stick click) | `R3` `RS` | `BTN_THUMBR` |
| `0x00010000` | Select / Back / Share | `SELECT` `BACK` `SHARE` | `BTN_SELECT` |
| `0x00020000` | Start / Menu / Options | `START` `MENU` `OPTIONS` | `BTN_START` |
| `0x00040000` | P1 — rear paddle, bottom-left | `P1` | `BTN_TRIGGER_HAPPY1` |
| `0x00080000` | P2 — rear paddle, bottom-right | `P2` | `BTN_TRIGGER_HAPPY2` |
| `0x00100000` | P3 — rear paddle, top-left | `P3` | `BTN_TRIGGER_HAPPY3` |
| `0x00200000` | P4 — rear paddle, top-right | `P4` | `BTN_TRIGGER_HAPPY4` |
| `0x00400000` | S1 — SAX left grip | `S1` | `BTN_TRIGGER_HAPPY5` |
| `0x00800000` | S2 — SAX right grip | `S2` | `BTN_TRIGGER_HAPPY6` |
| `0x01000000` | Home / PS / Xbox / Power | `HOME` `PS` `XBOX` `POWER` `PWR` | `BTN_MODE` |
| `0x04000000` | G1 | `G1` | `BTN_TRIGGER_HAPPY7` |
| `0x08000000` | G2 | `G2` | `BTN_TRIGGER_HAPPY8` |
| `0x10000000` | G3 | `G3` | `BTN_TRIGGER_HAPPY9` |
| `0x20000000` | G4 | `G4` | `BTN_TRIGGER_HAPPY10` |
| `0x40000000` | G5 | `G5` | `BTN_TRIGGER_HAPPY11` |
| `0x80000000` | Profile button | `PROFILE` | `BTN_TRIGGER_HAPPY12` |

DPAD bits (0x01–0x08) are summed per-axis, so diagonal inputs set both axes
simultaneously. All other bits are emitted as EV_KEY press/release events.

All **Config alias** names are case-insensitive in `config.ini`. Raw evdev names
(`BTN_SOUTH`, `BTN_TL`, etc.) are also accepted everywhere an alias works.

### Trigger Packet (`data[2] == 0x0a`)

| Bytes | Value | Virtual output | Range |
|---|---|---|---|
| `data[4:6]` | Left trigger (uint16 LE) | `ABS_Z` | 0 – 1023 |
| `data[6:8]` | Right trigger (uint16 LE) | `ABS_RZ` | 0 – 1023 |

### Analog Stick Packet (interface 3 hidraw)

Packets are 64 bytes. Bytes 1–8 carry four signed 16-bit little-endian values:

| Bytes | Axis | Virtual output | Range |
|---|---|---|---|
| `data[1:3]` | Left stick X | `ABS_X` | −32768 – 32767 |
| `data[3:5]` | Left stick Y | `ABS_Y` | −32768 – 32767 |
| `data[5:7]` | Right stick X | `ABS_RX` | −32768 – 32767 |
| `data[7:9]` | Right stick Y | `ABS_RY` | −32768 – 32767 |

### Outgoing Command Packets

All OUT reports are 64 bytes with OLH framing: `[0x02, endpoint, cmd..., 0x00×pad]`.

| Endpoint byte | Connection |
|---|---|
| `0x08` | Wired USB |
| `0x09` | Wireless dongle |

| Command bytes | Purpose | Notes |
|---|---|---|
| `0x01 0x03 0x00 0x02` | Software mode | Required before battery or RGB; sent once on open |
| `0x02 0x0f` | Battery query | Response arrives as `data[0]==0x03, data[3]==0x0f`; value at `data[4:6]` ÷ 10 = % |
| `0x12` | Keepalive / heartbeat | Sent every 20 s to prevent wireless timeout |
| `0x0d 0x00 0x01` | Open LED endpoint | RGB init step 1 |
| `0x01 0xc0 0x00 0x01` | Activate trigger backend | RGB init step 2 |
| `0x01 0x0b 0x00 0x00` | Disable eco mode | RGB init step 3; enables LEDs |
| `0x06 0x00 [len_lo] [len_hi] 0x00 0x00 [27 bytes]` | Write RGB frame | 27-byte planar buffer: R×9, G×9, B×9 |

**Profile remapping codes** (use any of these as keys/values in `[profile.NAME]`):

| Button | Primary alias | Additional aliases | Raw evdev code |
|---|---|---|---|
| Cross / A | `CROSS` | `A` | `BTN_SOUTH` |
| Circle / B | `CIRCLE` | `B` | `BTN_EAST` |
| Square / X | `SQUARE` | `X` | `BTN_NORTH` |
| Triangle / Y | `TRIANGLE` | `Y` | `BTN_WEST` |
| L1 | `L1` | `LB` | `BTN_TL` |
| R1 | `R1` | `RB` | `BTN_TR` |
| L3 | `L3` | `LS` | `BTN_THUMBL` |
| R3 | `R3` | `RS` | `BTN_THUMBR` |
| Select | `SELECT` | `BACK` `SHARE` | `BTN_SELECT` |
| Start | `START` | `MENU` `OPTIONS` | `BTN_START` |
| Home | `HOME` | `PS` `XBOX` `POWER` `PWR` | `BTN_MODE` |
| Paddle 1 | `P1` | — | `BTN_TRIGGER_HAPPY1` |
| Paddle 2 | `P2` | — | `BTN_TRIGGER_HAPPY2` |
| Paddle 3 | `P3` | — | `BTN_TRIGGER_HAPPY3` |
| Paddle 4 | `P4` | — | `BTN_TRIGGER_HAPPY4` |
| SAX left grip | `S1` | — | `BTN_TRIGGER_HAPPY5` |
| SAX right grip | `S2` | — | `BTN_TRIGGER_HAPPY6` |
| G1–G5 | `G1`–`G5` | — | `BTN_TRIGGER_HAPPY7`–`11` |
| Profile button | `PROFILE` | — | `BTN_TRIGGER_HAPPY12` |

---

## Supported Hardware

| Device | VID:PID | Connection | Status |
|---|---|---|---|
| SCUF Envision Pro Controller V2 | `1b1c:3a05` | Wired USB | Supported |
| SCUF Envision Pro Wireless USB Receiver V2 | `1b1c:3a08` | Wireless Dongle | Supported |

---

## Project Structure

```
scuf-envision-pro-V2-Linux/
  scuf_envision/
    __main__.py         # Entry point: python -m scuf_envision
    constants.py        # VID:PID, button/axis mapping tables
    discovery.py        # Auto-detect controller via sysfs
    bridge.py           # Core event loop + IPC socket + profile switching
    input_filter.py     # Radial deadzone, anti-deadzone, jitter suppression
    virtual_gamepad.py  # Virtual Xbox controller via uinput
    rumble.py           # FF event → HID motor packet translation
    config.py           # Config loading; named profiles; input_params() accessor
    audio_control.py    # USB audio unbind/rebind via sysfs
    hid.py              # HID raw: battery, RGB animation engine, rumble, keepalive
  tools/
    diag.py             # Live event diagnostic; --deadzone mode
    setup_scuf_audio.sh # Headphone audio setup (WirePlumber software volume)
    scuf-audio-toggle   # CLI: disable/enable SCUF audio
    scuf-ctl            # CLI: IPC client (profile switch, RGB, status, ping)
    scuf-profile        # Launch wrapper: activate profile, restore on exit
    tray.py             # System tray app (PyQt6 + pillow)
    scuf-tray.desktop   # XDG autostart entry for tray app
  config.ini.default    # Default config template
  50-scuf-audio.conf    # WirePlumber config for headphone audio
  99-scuf-envision.rules
  scuf-envision.service
  install.sh
  uninstall.sh
```

---

## Planned Features

| Phase | Feature |
|---|---|
| 16 | **Layers** — multiple button maps per profile; switch layers by holding a paddle; notification shows active layer name |
| 17 | **Macros** — bind a button to a sequence of inputs with optional delays |
| 18 | **Desktop layer** — persistent base layer across all profiles for window switching, media keys, etc. |
| 19 | **On-screen keyboard** — invoke system OSK from a button bind *(blocked: waiting on xdg-desktop-portal gamepad input portal)* |
| 20 | **DS4 / DualSense emulation** — optional alternative virtual device target; shows PlayStation button prompts in games |
| 21 | **Config GUI** — PyQt6 settings window for editing profiles, button remaps, deadzones, response curves, RGB, and triggers without touching config files; live apply via IPC |

---

## Credits

Mapping data verified against:
- [Scufpad](https://github.com/ChaseDRedmon/Scufpad) (C#/.NET) by ChaseDRedmon
- [cacique-envision-pro-linux](https://github.com/Gicotto/cacique-envision-pro-linux) (Python) by Gicotto

HID/USB protocol research and hidraw rumble packet implementation informed by:
- [OpenLinkHub](https://github.com/jurkovic-nikola/OpenLinkHub) by jurkovic-nikola — a comprehensive open-source Linux driver for Corsair USB devices. Its HID protocol work, device communication patterns, and [SCUF controller audio fix](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/docs/scuf-controller.md) (`amixer cset numid=8 32,32` + `api.alsa.use-acp = false`) were valuable references.

## License

GPLv3 - see [LICENSE](LICENSE)
