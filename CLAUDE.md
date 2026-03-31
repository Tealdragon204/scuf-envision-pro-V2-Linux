# CLAUDE.md — SCUF Envision Pro V2 Linux Driver

Python userspace driver (`scuf_envision`) that remaps the SCUF Envision Pro V2's
non-standard evdev output to a correct Xbox-compatible virtual gamepad via uinput.
Also handles USB audio quirks and wireless reconnection.

**Goal:** reach feature parity with OpenLinkHub's SCUF controller support —
RGB, button remapping, vibration, triggers, battery — without requiring OLH.

## Session Rules

- Grep first. Read whole files only when grep is insufficient.
- For Phase N work, read only files listed in that phase's row below.
- Skip `README.md` for implementation tasks.

## Coding Standards

- **Concise over verbose**: fewer lines that do the job > more lines that are "clear". Prefer comprehensions, early returns, and unpacking over explicit loops and temp vars.
- **No redundant comments**: comment only on *why* a choice was made or *how* a piece connects to its caller/callee if non-obvious. Never restate what the code does.
- **Inline docs as written**: docstrings on non-trivial public functions only; describe behaviour and side-effects, not implementation.
- **No defensive boilerplate**: trust the type system and callers; omit guards that can't actually trigger.

## Architecture

```
Physical SCUF Controller (VID 1b1c, PID 3a05 wired / 3a08 wireless)
        │
        ├─── evdev interface (/dev/input/eventN)
        │         │
        │    discovery.py ── sysfs VID:PID scan ──► /dev/input/eventN
        │         │
        │    bridge.py ── exclusive evdev grab
        │         │
        │    ├── input_filter.py ── deadzone, jitter
        │    ├── constants.py ── remap tables
        │    └── virtual_gamepad.py ── uinput ──► Virtual Xbox controller ──► Games
        │
        └─── HID raw interface (/dev/hidrawN) ← Phase 9+
                  │
            hid.py (future) ── battery, RGB, vibration, trigger config
```

`config.py` is read at startup. `audio_control.py` handles USB audio bind/unbind
independently via sysfs. Wireless: `bridge.py` keeps the virtual gamepad alive for
up to 5 min while waiting for controller reconnection.

## Phase Map

| Phase | Goal | Status | Key Files |
|-------|------|--------|-----------|
| 0 | Project scaffolding | ✅ | — |
| 1 | Core driver (detection, remap, virtual gamepad) | ✅ | `constants.py`, `discovery.py`, `bridge.py`, `virtual_gamepad.py` |
| 2 | Input filtering (deadzone, jitter) | ✅ | `input_filter.py` |
| 3 | Config system | ✅ | `scuf_envision/config.py` |
| 4 | Audio support v1 (WirePlumber ACP disable, CLI toggle) | ✅ | `audio_control.py`, `tools/scuf-audio-toggle`, `50-scuf-audio.conf` |
| 5 | Wireless support (auto-reconnect loop) | ✅ | `bridge.py` |
| 6 | Installer + systemd service | ✅ | `install.sh`, `uninstall.sh`, `scuf-envision.service` |
| 7 | Diagnostics | ✅ | `tools/diag.py` |
| 8 | Audio fix v2 (amixer numid=8 volume + serial-aware WirePlumber config) | Planned | `install.sh`, `50-scuf-audio.conf`, `tools/setup_scuf_audio.sh` |
| 9 | Battery detection | Planned | `scuf_envision/hid.py` (new) |
| 10 | OpenLinkHub coexistence (disable OLH virtual gamepad; keep HID layer ours) | ⚠️ Partial | `bridge.py`, `scuf_envision/discovery.py` — grab suppresses OLH's uinput gamepad; HID-layer conflict (duplicate keepalives when OLH runs) unresolved |
| 11 | Button remapping + per-game profiles | Planned | `scuf_envision/config.py`, `bridge.py`, `constants.py` |
| 12 | RGB control | Planned | `scuf_envision/hid.py` |
| 13 | Vibration/haptics passthrough | Planned | `scuf_envision/hid.py`, `virtual_gamepad.py` |
| 14 | Trigger configuration (curve, deadzone per-trigger) | Planned | `scuf_envision/hid.py`, `input_filter.py` |
| 15 | Tray app | Planned | `tools/tray.py` (new) |

## Known Platform Constraints

- **Exclusive evdev grab is mandatory** — `device.grab()` must happen before the
  uinput device is created. Without it, the kernel and the virtual gamepad both
  emit events simultaneously, causing double-input. Do not make this conditional.

- **Audio fix is two separate operations** — the SCUF audio interface has two
  distinct problems:
  1. **Volume level** — ALSA mixer `numid=8` defaults to 16,16 (50% power). Must
     be set to 32,32 via `amixer -D hw:<card> cset numid=8 32,32 && alsactl store`.
     Card name differs: wired = `V2`, wireless = `USB`.
  2. **Volume control** — PipeWire/WirePlumber tries to use the hardware ACP, which
     has a broken dB range. Fix: WirePlumber config with `api.alsa.use-acp = false`
     and `api.alsa.soft-mixer/soft-vol = true`. The `device.name` key must match the
     user's serial number — it cannot be hardcoded. `install.sh` must discover it at
     install time via `pactl list sinks`.
  Both fixes must be applied. Phase 4 only implemented #2 (approximately). Phase 8
  completes both properly, for wired and wireless separately.

- **OpenLinkHub creates a competing virtual gamepad** — OLH registers its own HID
  gamepad for the SCUF. To coexist, OLH's virtual gamepad must be disabled. Our
  exclusive evdev grab handles the raw device side, but OLH's gamepad runs at the
  HID layer independently. Phase 10 resolves this.

- **HID raw interface needed for non-evdev features** — battery, RGB, vibration,
  and trigger configuration all require sending/receiving HID reports via
  `/dev/hidrawN`, not the evdev interface. Phase 9+ adds `hid.py` for this.
  The hidraw node for the SCUF is identified by VID:PID via sysfs (same discovery
  pattern as evdev in `discovery.py`).

- **uinput module must be loaded** — `modprobe uinput` at runtime, persisted via
  `/etc/modules-load.d/uinput.conf`. Installer handles this; manual runs need it
  explicitly.

- **Wireless reconnect: keep vgamepad alive** — when the wireless controller
  disconnects (power off, range, sleep), the virtual gamepad must not be destroyed.
  Games treat device removal as controller unplug. `bridge.py` waits up to 5 min
  for reconnection before tearing down.

- **SDL double-input** — SDL reads both the raw SCUF device and our virtual Xbox
  gamepad. Users must set `SDL_GAMECONTROLLER_IGNORE_DEVICES=0x1b1c/0x3a05` in
  `~/.config/environment.d/scuf.conf` (KDE/Wayland env, not `.bashrc`). Installer
  writes this file.

- **udev rule required for non-root** — `99-scuf-envision.rules` must be installed
  and `udevadm trigger` run before unprivileged access to `/dev/input/eventN` and
  `/dev/hidrawN` works. The service runs as root; manual dev runs need `sudo`.

## File Responsibilities

| File | Responsibility |
|------|----------------|
| `scuf_envision/__main__.py` | Entry point: `python -m scuf_envision`; arg parsing, logging setup |
| `scuf_envision/constants.py` | VID:PID definitions; button and axis remap tables (SCUF → Xbox) |
| `scuf_envision/discovery.py` | Auto-detect controller via sysfs VID:PID scan; returns evdev + hidraw paths |
| `scuf_envision/bridge.py` | Core event loop: exclusive grab → read raw events → remap → emit; wireless reconnect loop |
| `scuf_envision/input_filter.py` | Radial deadzone computation, jitter suppression |
| `scuf_envision/virtual_gamepad.py` | Creates and manages virtual Xbox controller via uinput |
| `scuf_envision/config.py` | Loads `/etc/scuf-envision/config.ini`; typed config dataclass |
| `scuf_envision/audio_control.py` | USB audio interface bind/unbind via sysfs; persists state to config |
| `scuf_envision/hid.py` | (Phase 9+) HID raw interface: battery, RGB, vibration, trigger config |
| `tools/diag.py` | Raw event diagnostic: prints SCUF→Xbox remapping live; Ctrl-C to exit |
| `tools/setup_scuf_audio.sh` | Audio fix: amixer numid=8 32,32 + serial-aware WirePlumber ACP config |
| `tools/scuf-audio-toggle` | CLI: `disable` / `enable` / `status` for SCUF USB audio interface |
| `tools/tray.py` | (Phase 15) System tray app |
| `50-scuf-audio.conf` | WirePlumber config template: forces software volume on SCUF headset mixer |
| `99-scuf-envision.rules` | udev rules: grants non-root access to SCUF evdev + hidraw nodes |
| `scuf-envision.service` | systemd service unit (runs as root, auto-starts on boot) |
| `install.sh` | Full installer: deps, udev, uinput, audio fix, SDL env, service |
| `uninstall.sh` | Full uninstaller: reverses all install changes, preserves config |
| `config.ini.default` | Default config template (copied to `/etc/scuf-envision/` on install) |
