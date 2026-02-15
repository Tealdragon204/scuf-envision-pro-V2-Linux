# SCUF Envision Pro V2 - Linux Driver

A userspace driver that makes the SCUF Envision Pro V2 controller work correctly on Linux with proper Xbox button mapping.

**Tested on:** Garuda Linux (Arch-based) with KDE Plasma

## The Problem

The SCUF Envision Pro V2 (Corsair VID `1b1c`, PID `3a05`) sends **wildly non-standard evdev button and axis codes** on Linux. Without this driver, buttons are mismatched (X/Y swapped, bumpers in wrong slots, triggers on wrong axes) and games are unplayable.

Additionally, the controller's USB audio "Headset" mixer reports a broken dB range, causing volume control to not work under PipeWire/WirePlumber without the included audio fix.

## How It Works

```
Physical SCUF Controller (broken mapping)
        |
        v
  Auto-detection (sysfs VID:PID scan)
        |
        v
  Exclusive grab (prevents double-input)
        |
        v
  Button/Axis remapping (SCUF -> Xbox standard)
        |
        v
  Deadzone & jitter filtering
        |
        v
  Virtual Xbox Gamepad (via uinput)
        |
        v
  Games & Steam see a normal Xbox controller
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

### Step 2: Install Dependencies

**Arch / Garuda / Manjaro:**
```bash
sudo pacman -S python-evdev
```

**Ubuntu / Debian / Pop!_OS:**
```bash
sudo apt install python3-evdev
```

**Fedora:**
```bash
sudo dnf install python3-evdev
```

### Step 3: Load the uinput Kernel Module

The driver needs `uinput` to create a virtual gamepad. Load it now and make it persist across reboots:

```bash
# Load it now
sudo modprobe uinput

# Make it load automatically on boot
echo 'uinput' | sudo tee /etc/modules-load.d/uinput.conf
```

### Step 4: Install udev Rules (Recommended)

This grants your user permission to access the controller devices without needing `sudo` every time:

```bash
sudo cp 99-scuf-envision.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Step 5: Enable Headphone Audio (Recommended)

The SCUF controller has a built-in headphone jack, but its USB audio "Headset" mixer reports an invalid dB range. PipeWire/WirePlumber disables dB-based volume mapping, making the volume slider cosmetic-only (only mute actually works).

This one-time fix installs a WirePlumber config that forces software volume mixing:

```bash
sudo bash tools/setup_scuf_audio.sh
```

Then **reboot** (or run `systemctl --user restart wireplumber` as your normal user). After that, the headphone volume slider will work normally. The udev rules also auto-set the hardware mixer to max on each connect.

To undo:

```bash
sudo rm /etc/wireplumber/wireplumber.conf.d/50-scuf-audio.conf
sudo udevadm control --reload-rules
# Then reboot or restart WirePlumber
```

---

## Usage

### Quick Test: Diagnostic Tool

Before running the full driver, plug in your controller via USB and run the diagnostic tool to see raw events:

```bash
sudo python3 tools/diag.py
```

This shows every button press and stick movement with labels showing what the SCUF sends vs what it should send. Press each button and move each stick to verify everything is detected. Press **Ctrl+C** to exit.

### Running the Driver (Manual)

```bash
cd scuf-envision-pro-V2-Linux
sudo python3 -m scuf_envision
```

You should see output like:

```
12:00:00 [INFO] scuf_envision.bridge: SCUF Envision Pro V2 Linux Driver starting...
12:00:00 [INFO] scuf_envision.discovery: SCUF primary gamepad: /dev/input/event26
12:00:00 [INFO] scuf_envision.bridge: Exclusively grabbed: Scuf Gaming SCUF Envision Pro Controller V2
12:00:00 [INFO] scuf_envision.virtual_gamepad: Created virtual gamepad: /dev/input/event27
12:00:00 [INFO] scuf_envision.bridge: Bridge started - SCUF -> Xbox translation active
```

The driver runs until you press **Ctrl+C** or unplug the controller.

### Verify It's Working

With the driver running, open another terminal:

```bash
# You should see the virtual Xbox controller listed
cat /proc/bus/input/devices | grep -A5 "SCUF Envision Pro V2 (Xbox Mode)"

# Or test with evtest (install: sudo pacman -S evtest)
sudo evtest
# Select the "SCUF Envision Pro V2 (Xbox Mode)" device
```

### Running as a Systemd Service (Auto-Start)

To have the driver start automatically when you plug in the controller:

```bash
# One-time install using the install script
sudo bash install.sh

# Or manually install the service
sudo cp scuf-envision.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable and start
sudo systemctl enable --now scuf-envision.service

# Check status
sudo systemctl status scuf-envision.service

# View logs
journalctl -u scuf-envision.service -f
```

To stop:

```bash
sudo systemctl stop scuf-envision.service
```

---

## Steam Configuration

Steam's built-in controller support may try to read the raw SCUF device (with broken mappings) alongside our virtual Xbox controller, causing double-input or conflicting mappings.

### Option A: Environment Variable (Recommended)

Tell SDL to ignore the physical SCUF device entirely:

```bash
# Create environment config (works with KDE Plasma, GNOME, etc.)
mkdir -p ~/.config/environment.d
echo 'SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05' > ~/.config/environment.d/scuf.conf
```

Log out and back in for this to take effect.

### Option B: Steam Settings

1. Open Steam -> Settings -> Controller -> General Controller Settings
2. Find the SCUF Envision Pro entry (if listed) and disable it
3. The virtual "SCUF Envision Pro V2 (Xbox Mode)" controller should be listed as an Xbox controller

---

## Automated Install / Uninstall

### Full Install

```bash
sudo bash install.sh
```

This does everything in one step:
- Installs `python-evdev`
- Loads `uinput` kernel module (persists across reboots)
- Installs udev rules
- Copies the driver to `/opt/scuf-envision`
- Installs the systemd service
- Installs audio config (WirePlumber software volume fix)

### Full Uninstall

```bash
sudo bash uninstall.sh
```

Removes the service, udev rules, and installed files. Does not remove `python-evdev` or the `uinput` module.

---

## Complete Uninstallation & Reversal Guide

If the driver doesn't work for you or you simply want to remove it, follow this guide to undo **every change** made during installation. After completing these steps your system will be exactly as it was before.

### Step 1: Stop and Remove the Systemd Service

If you set up the driver as a service:

```bash
# Stop the running service
sudo systemctl stop scuf-envision.service

# Disable it from starting on boot
sudo systemctl disable scuf-envision.service

# Remove the service file
sudo rm -f /etc/systemd/system/scuf-envision.service

# Reload systemd so it forgets the service
sudo systemctl daemon-reload
```

If you were running the driver manually (not as a service), just press **Ctrl+C** in the terminal where it's running to stop it.

### Step 2: Remove the Driver Files

If you used `install.sh`, the driver was copied to `/opt/scuf-envision`:

```bash
sudo rm -rf /opt/scuf-envision
```

### Step 3: Remove udev Rules

The installation created up to two udev rule files:

```bash
# Remove the device permission rules
sudo rm -f /etc/udev/rules.d/99-scuf-envision.rules

# Remove the audio config (if you ran setup_scuf_audio.sh)
sudo rm -f /etc/wireplumber/wireplumber.conf.d/50-scuf-audio.conf

# Reload udev so the rules take effect immediately
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Step 4: Remove the uinput Auto-Load Config

The installation configured the `uinput` kernel module to load automatically on boot. To undo this:

```bash
sudo rm -f /etc/modules-load.d/uinput.conf
```

> **Note:** Other software may also use `uinput` (e.g., other controller drivers, remote desktop tools). If you're unsure, you can leave this file in place - it's harmless.

### Step 5: Remove the SDL Environment Variable (Steam Fix)

If you set the SDL ignore variable for Steam:

```bash
rm -f ~/.config/environment.d/scuf.conf
```

Log out and back in for this change to take effect.

### Step 6: Remove the python-evdev Package (Optional)

This is optional because `python-evdev` is a common package that other software may depend on.

**Arch / Garuda / Manjaro:**
```bash
sudo pacman -Rs python-evdev
```

**Ubuntu / Debian / Pop!_OS:**
```bash
sudo apt remove python3-evdev
```

**Fedora:**
```bash
sudo dnf remove python3-evdev
```

### Step 7: Delete the Cloned Repository (Optional)

```bash
rm -rf ~/scuf-envision-pro-V2-Linux
```

### Quick Uninstall (All-in-One)

If you want to remove everything in one go, you can run these commands back-to-back:

```bash
# Stop and remove service
sudo systemctl stop scuf-envision.service 2>/dev/null; true
sudo systemctl disable scuf-envision.service 2>/dev/null; true
sudo rm -f /etc/systemd/system/scuf-envision.service
sudo systemctl daemon-reload

# Remove installed driver files
sudo rm -rf /opt/scuf-envision

# Remove all udev rules
sudo rm -f /etc/udev/rules.d/99-scuf-envision.rules
sudo rm -f /etc/wireplumber/wireplumber.conf.d/50-scuf-audio.conf
sudo udevadm control --reload-rules
sudo udevadm trigger

# Remove uinput auto-load
sudo rm -f /etc/modules-load.d/uinput.conf

# Remove SDL ignore variable
rm -f ~/.config/environment.d/scuf.conf

echo "All SCUF driver components removed."
```

After this, **unplug and replug** the controller and **log out / log back in** to ensure all changes take effect. Your controller will go back to its default (unmapped) Linux behavior.

### What the Uninstall Does NOT Change

For safety, the uninstall process does **not** touch these:
- **python-evdev package** - other software may use it; remove manually if you want (see Step 6)
- **uinput kernel module** - it's a standard Linux module; removing the auto-load config just prevents it from loading on boot, it doesn't uninstall it
- **Your Steam library or game configs** - no game settings are modified by this driver

---

## Troubleshooting

### Controller not detected

```
ERROR: No SCUF Envision Pro V2 controller found!
```

1. **Check USB connection:** `lsusb | grep 1b1c` - you should see `1b1c:3a05` (wired) or `1b1c:3a08` (wireless receiver)
2. **Try a different USB port** - preferably a port directly on the motherboard, not a hub
3. **Try a different USB cable** - a bad cable can cause intermittent detection
4. **Check dmesg:** `dmesg | tail -20` - look for USB errors

### Controller disconnects after a few seconds

This can be caused by the USB audio interface. Make sure the audio setup is applied:

```bash
sudo bash tools/setup_scuf_audio.sh
# Reboot or restart WirePlumber, then replug the controller
```

### Double input / buttons firing twice

The driver exclusively grabs the physical device to prevent this. If it still happens:

1. Make sure only one instance of the driver is running
2. Set the SDL ignore variable (see Steam Configuration above)
3. Check: `cat /proc/bus/input/devices | grep -c "SCUF"` - should show 2 entries (physical + virtual), not more

### Permission denied errors

```bash
# Make sure udev rules are installed
sudo cp 99-scuf-envision.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# Or just run with sudo
sudo python3 -m scuf_envision
```

### "uinput" module not found

```bash
sudo modprobe uinput
echo 'uinput' | sudo tee /etc/modules-load.d/uinput.conf
```

### Wireless: controller not detected

1. **Check receiver:** `lsusb | grep 1b1c` - you should see `1b1c:3a08` for the wireless receiver
2. **Power on the controller** - the receiver only exposes gamepad inputs when the controller is paired and powered on
3. **Re-pair if needed** - hold the pairing button on the receiver, then hold the pairing button on the controller
4. **Run diagnostics:** `sudo python3 tools/diag.py` - it will show both wired and wireless devices

### Wireless: controller reconnection

When using the wireless receiver, the driver automatically waits up to 5 minutes for the controller to reconnect if it disconnects (powered off, out of range, or sleeping). The virtual gamepad stays alive during this time so games don't see a device removal. To verify reconnection is working, check the driver logs:

```bash
sudo journalctl -u scuf-envision.service -f
# Look for: "Controller disconnected. Waiting for reconnection..."
# Then:     "Controller reconnected!"
```

---

## Button Mapping Reference

### Buttons

| Physical Button | SCUF Sends (Wrong) | Driver Outputs (Correct) |
|---|---|---|
| A | BTN_SOUTH (0x130) | BTN_SOUTH (0x130) |
| B | BTN_EAST (0x131) | BTN_EAST (0x131) |
| X | BTN_C (0x132) | BTN_NORTH (0x133) — kernel alias BTN_X |
| Y | BTN_NORTH (0x133) | BTN_WEST (0x134) — kernel alias BTN_Y |
| LB (Left Bumper) | BTN_WEST (0x134) | BTN_TL (0x136) |
| RB (Right Bumper) | BTN_Z (0x135) | BTN_TR (0x137) |
| Select / Back | BTN_TL (0x136) | BTN_SELECT (0x13a) |
| Start / Menu | BTN_TR (0x137) | BTN_START (0x13b) |
| L3 (Left Stick Click) | BTN_TL2 (0x138) | BTN_THUMBL (0x13d) |
| R3 (Right Stick Click) | BTN_TR2 (0x139) | BTN_THUMBR (0x13e) |
| Xbox / Guide | BTN_MODE (0x13c) | BTN_MODE (0x13c) |
| Paddle 1 | BTN_TRIGGER_HAPPY1 | BTN_TRIGGER_HAPPY1 |
| Paddle 2 | BTN_TRIGGER_HAPPY2 | BTN_TRIGGER_HAPPY2 |
| Paddle 3 | BTN_TRIGGER_HAPPY3 | BTN_TRIGGER_HAPPY3 |

### Axes

| Physical Input | SCUF Sends (Wrong) | Driver Outputs (Correct) | Range |
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
  scuf_envision/              # Main driver package
    __init__.py
    __main__.py               # Entry point: python -m scuf_envision
    constants.py              # VID:PID, button/axis mapping tables
    discovery.py              # Auto-detect controller via sysfs
    bridge.py                 # Core event loop (read -> remap -> emit)
    input_filter.py           # Radial deadzone, jitter suppression
    virtual_gamepad.py        # Virtual Xbox controller via uinput
  tools/
    diag.py                   # Raw event diagnostic tool
    setup_scuf_audio.sh       # Headphone audio setup (WirePlumber software volume)
  50-scuf-audio.conf           # WirePlumber config for headphone audio
  99-scuf-envision.rules      # udev rules for device permissions
  scuf-envision.service       # systemd service file
  install.sh                  # Automated installer
  uninstall.sh                # Automated uninstaller
```

## Credits

Mapping data verified against:
- [Scufpad](https://github.com/ChaseDRedmon/Scufpad) (C#/.NET) by ChaseDRedmon
- [cacique-envision-pro-linux](https://github.com/Gicotto/cacique-envision-pro-linux) (Python) by Gicotto

## License

GPLv3 - see [LICENSE](LICENSE)
