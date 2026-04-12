# SCUF Envision Pro V2 - Linux Driver

A userspace driver that makes the SCUF Envision Pro V2 controller work correctly on Linux with proper Xbox button mapping, RGB control, rumble, profiles, and more.

**Tested on:** Garuda Linux (Arch-based) with KDE Plasma

## Features

- **Button/axis remapping** — corrects the controller's non-standard evdev output to Xbox-compatible codes
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
        |           |
        |     Auto-detection (sysfs VID:PID scan)
        |           |
        |     Exclusive grab (prevents double-input)
        |           |
        |     Profile-based button/axis remapping
        |           |
        |     Deadzone, anti-deadzone & jitter filtering
        |           |
        |     Virtual Xbox Gamepad (via uinput)
        |           |
        |     Games & Steam see a normal Xbox controller
        |
        +--- HID raw interface (/dev/hidrawN)
                    |
                    +-- Battery polling (every 60s) -> desktop notifications
                    |
                    +-- RGB animation engine (software, 60 fps)
                    |
                    +-- Rumble: game FF_RUMBLE events -> HID motor packet
                    |
                    +-- Keepalive (every 20s, wireless)
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
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
BTN_TRIGGER_HAPPY2 = BTN_EAST
BTN_TRIGGER_HAPPY3 = BTN_NORTH

# Swap A and B (Nintendo muscle memory)
[profile.NINTENDO_LAYOUT]
BTN_SOUTH = BTN_EAST
BTN_EAST  = BTN_SOUTH
```

Keys are the raw SCUF hardware codes; values are what games receive. See [Button Mapping Reference](#button-mapping-reference) for the full code list.

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

## Button Mapping Reference

### Buttons

| Physical Button | SCUF Sends (Wrong) | Driver Outputs (Correct) |
|---|---|---|
| A | BTN_SOUTH (0x130) | BTN_SOUTH (0x130) |
| B | BTN_EAST (0x131) | BTN_EAST (0x131) |
| X | BTN_C (0x132) | BTN_NORTH (0x133) |
| Y | BTN_NORTH (0x133) | BTN_WEST (0x134) |
| LB | BTN_WEST (0x134) | BTN_TL (0x136) |
| RB | BTN_Z (0x135) | BTN_TR (0x137) |
| Select / Back | BTN_TL (0x136) | BTN_SELECT (0x13a) |
| Start / Menu | BTN_TR (0x137) | BTN_START (0x13b) |
| L3 | BTN_TL2 (0x138) | BTN_THUMBL (0x13d) |
| R3 | BTN_TR2 (0x139) | BTN_THUMBR (0x13e) |
| Guide | BTN_MODE (0x13c) | BTN_MODE (0x13c) |
| Paddle 1 | BTN_TRIGGER_HAPPY1 | BTN_TRIGGER_HAPPY1 |
| Paddle 2 | BTN_TRIGGER_HAPPY2 | BTN_TRIGGER_HAPPY2 |
| Paddle 3 | BTN_TRIGGER_HAPPY3 | BTN_TRIGGER_HAPPY3 |

**Physical codes for profile remapping** (what to use as keys in `[profile.NAME]`):

```
BTN_SOUTH, BTN_EAST, BTN_C (X), BTN_NORTH (Y),
BTN_WEST (LB), BTN_Z (RB), BTN_TL (Back), BTN_TR (Start),
BTN_TL2 (L3), BTN_TR2 (R3), BTN_MODE (Guide),
BTN_TRIGGER_HAPPY1/2/3 (Paddles)
```

**Virtual output codes** (what to use as values):

```
BTN_SOUTH (A), BTN_EAST (B), BTN_NORTH (X), BTN_WEST (Y),
BTN_TL (LB), BTN_TR (RB), BTN_SELECT (Back), BTN_START (Start),
BTN_THUMBL (L3), BTN_THUMBR (R3), BTN_MODE (Guide),
BTN_TRIGGER_HAPPY1/2/3 (Paddles)
```

### Axes

| Physical Input | SCUF Sends | Driver Outputs | Range |
|---|---|---|---|
| Left Stick X | ABS_X | ABS_X | -32768 to 32767 |
| Left Stick Y | ABS_Y | ABS_Y | -32768 to 32767 |
| Right Stick X | ABS_Z | ABS_RX | -32768 to 32767 |
| Right Stick Y | ABS_RZ | ABS_RY | -32768 to 32767 |
| Left Trigger | ABS_RX | ABS_Z | 0 to 1023 |
| Right Trigger | ABS_RY | ABS_RZ | 0 to 1023 |
| D-Pad X | ABS_HAT0X | ABS_HAT0X | -1 to 1 |
| D-Pad Y | ABS_HAT0Y | ABS_HAT0Y | -1 to 1 |

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
