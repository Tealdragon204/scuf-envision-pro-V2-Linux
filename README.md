# SCUF Envision Pro V2 - Linux Driver

A userspace driver that makes the SCUF Envision Pro V2 controller work correctly on Linux with proper Xbox button mapping.

## The Problem

The SCUF Envision Pro V2 (Corsair VID `1b1c`, PID `3a05`) sends **wildly non-standard evdev button and axis codes** on Linux. Without this driver, buttons are mismatched (X/Y swapped, bumpers in wrong slots, triggers on wrong axes) and games are unplayable.

Additionally, the controller's USB audio interfaces (headphone jack) can cause USB protocol errors that destabilize the connection.

## How It Works

1. **Discovers** the controller via sysfs scanning (VID:PID match)
2. **Exclusively grabs** the physical device (prevents double-input)
3. **Remaps** all non-standard button/axis codes to Xbox standard
4. **Filters** inputs (radial deadzones, jitter suppression)
5. **Outputs** to a virtual Xbox gamepad via uinput

Games and Steam see a standard Xbox controller.

## Button Mapping

| Physical Button | SCUF Sends (Wrong) | Driver Outputs (Correct) |
|---|---|---|
| A | BTN_SOUTH | BTN_SOUTH |
| B | BTN_EAST | BTN_EAST |
| X | BTN_C | BTN_WEST |
| Y | BTN_NORTH | BTN_NORTH |
| LB | BTN_WEST | BTN_TL |
| RB | BTN_Z | BTN_TR |
| Select | BTN_TL | BTN_SELECT |
| Start | BTN_TR | BTN_START |
| L3 | BTN_TL2 | BTN_THUMBL |
| R3 | BTN_TR2 | BTN_THUMBR |

Axis remapping: Right stick X/Y and triggers are on swapped axis codes.

## Requirements

- Linux kernel with `uinput` module
- Python 3.8+
- `python-evdev` package

## Quick Start

```bash
# Install dependencies (Arch/Garuda)
sudo pacman -S python-evdev

# Load uinput module
sudo modprobe uinput

# Run diagnostic tool first (plug in controller, then run)
sudo python3 tools/diag.py

# Run the driver
sudo python3 -m scuf_envision
```

## Installation

```bash
sudo bash install.sh
```

This installs:
- udev rules for device permissions
- Driver to `/opt/scuf-envision`
- systemd service (optional)

## USB Audio Stability Fix

If your controller keeps disconnecting with dmesg errors like:
```
usb 3-6: 2:1: usb_set_interface failed (-71)
```

Run the audio interface workaround:
```bash
sudo bash tools/disable_scuf_audio.sh
```

This prevents the Linux audio driver from fighting with the controller's USB audio endpoints. The headphone jack won't work, but the gamepad will be stable.

## Steam Configuration

To prevent Steam from also reading the raw (unmapped) physical device:

```bash
# Add to your environment (e.g., ~/.config/environment.d/scuf.conf)
SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05
```

## Uninstall

```bash
sudo bash uninstall.sh
```

## Supported Hardware

| Device | VID:PID | Status |
|---|---|---|
| SCUF Envision Pro Controller V2 (wired) | `1b1c:3a05` | Supported |
| SCUF Envision Pro Wireless USB Receiver V2 | `1b1c:3a09` | Planned |

## Credits

Mapping data verified against:
- [Scufpad](https://github.com/ChaseDRedmon/Scufpad) (C#/.NET)
- [cacique-envision-pro-linux](https://github.com/Gicotto/cacique-envision-pro-linux) (Python)

## License

GPLv3 - see [LICENSE](LICENSE)
