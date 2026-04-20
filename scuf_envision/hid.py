"""
HID raw interface for the SCUF Envision Pro V2.

Phase 9: Battery level reading via the control HID interface.
"""

import os
import select
import struct
import subprocess
import threading
import time
import logging

from evdev import ecodes

from .constants import (RGB_CMD_OPEN_ENDPOINT, RGB_CMD_WRITE_COLOR, RGB_NUM_LEDS,
                        RGB_CMD_INIT_WRITE, RGB_CMD_TRIGGER_BACKEND, RGB_CMD_ECO_MODE_OFF,
                        _DZ_INIT, _DZ_MIN, _DZ_MAX,
                        HID_BUTTON_MAP, HID_DPAD, HID_BTN_MASK_OFFSET)

log = logging.getLogger(__name__)

_REPORT_SIZE     = 64
_CMD_SOFTWARE_MODE = bytes([0x01, 0x03, 0x00, 0x02])
_CMD_BATTERY       = bytes([0x02, 0x0f])
_CMD_KEEPALIVE     = bytes([0x12])

# Endpoint byte differs by connection type (OLH: 0x08 wired, 0x09 wireless dongle)
_ENDPOINT_WIRED    = 0x08
_ENDPOINT_WIRELESS = 0x09

_KEEPALIVE_INTERVAL  = 20.0   # seconds — matches OLH heartbeat
_BATTERY_INTERVAL    = 60.0   # seconds — re-poll battery level
_WARMUP_SECS         = 90.0   # BMS needs ~90s to converge SoC after connect


def _notify(title: str, body: str, urgency: str = "normal") -> None:
    """Send a desktop notification to the active graphical session user.

    Finds the first active graphical loginctl session, then runs notify-send
    as that user via runuser with the correct D-Bus session bus address.
    Silently skips if no graphical session or notify-send is unavailable.
    """
    try:
        sessions = subprocess.check_output(
            ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
            text=True, timeout=3,
        ).splitlines()
    except (FileNotFoundError, subprocess.SubprocessError):
        return

    for line in sessions:
        parts = line.split()
        if len(parts) < 2:
            continue
        session_id = parts[0]
        try:
            props = subprocess.check_output(
                ["loginctl", "show-session", session_id,
                 "--property=Type", "--property=Name", "--property=State",
                 "--property=RuntimePath"],
                text=True, timeout=3,
            )
        except subprocess.SubprocessError:
            continue

        prop = dict(p.split("=", 1) for p in props.splitlines() if "=" in p)
        if prop.get("Type") not in ("x11", "wayland") or prop.get("State") != "active":
            continue

        username = prop.get("Name", "")
        if not username:
            continue

        try:
            uid = subprocess.check_output(["id", "-u", username], text=True, timeout=3).strip()
        except subprocess.SubprocessError:
            continue

        # Prefer the XDG_RUNTIME_DIR reported by loginctl; fall back to convention
        runtime_dir = prop.get("RuntimePath") or f"/run/user/{uid}"
        dbus_addr = f"unix:path={runtime_dir}/bus"
        if not os.path.exists(f"{runtime_dir}/bus"):
            log.warning("D-Bus socket not found at %s — notification suppressed", dbus_addr)
            continue

        expire_ms = "10000"
        sound = "battery-caution" if urgency == "critical" else "audio-volume-change"
        env = {**os.environ, "DBUS_SESSION_BUS_ADDRESS": dbus_addr}
        log.debug("Sending notification via runuser as %s (bus: %s)", username, dbus_addr)
        try:
            result = subprocess.run(
                ["runuser", "-u", username, "--",
                 "notify-send", "--urgency", urgency,
                 "--expire-time", expire_ms,
                 "--app-name", "SCUF Controller",
                 "--icon", "battery-caution",
                 "--hint", f"string:sound-name:{sound}",
                 title, body],
                env=env, timeout=5, check=False,
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                log.warning("notify-send exited %d: %s", result.returncode,
                            (result.stderr or result.stdout).strip())
            else:
                log.info("Notification sent to %s", username)
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            log.warning("notify-send failed: %s", e)
        return  # only notify once (first active graphical session)


def _packet(endpoint: int, cmd: bytes) -> bytes:
    """Build a 64-byte HID OUT report with OLH framing: [0x02, endpoint, cmd...]."""
    buf = bytearray(64)
    buf[0] = 0x02
    buf[1] = endpoint
    buf[2:2 + len(cmd)] = cmd
    return bytes(buf)


def _read(fd: int, timeout: float) -> bytes:
    """Read one HID report with a timeout; returns empty bytes on timeout."""
    r, _, _ = select.select([fd], [], [], timeout)
    return os.read(fd, _REPORT_SIZE) if r else b''


def setup_analog_deadzones(hidraw_path: str, connection_type: str,
                           left_stick: int, right_stick: int,
                           left_trigger: int, right_trigger: int) -> None:
    """Send hardware deadzone registers to firmware. Values clamped to 0–15.

    WARNING: The _DZ_INIT/_DZ_MIN/_DZ_MAX byte sequences in constants.py have NOT
    been verified against a USB capture. Sending incorrect HID commands to the
    firmware can mute axis reporting on the physical device. Do NOT call this
    function until the byte sequences have been confirmed via Wireshark/USBmon
    by capturing OLH setting deadzone values and comparing the raw HID reports.

    Until verified, hardware deadzone config is intentionally not applied.
    Software deadzone (InputFilter) is used exclusively.
    """
    log.warning("setup_analog_deadzones() called but HW DZ byte sequences are unverified "
                "— skipping firmware write to avoid corrupting axis state")
    return
    endpoint = _ENDPOINT_WIRELESS if connection_type == "wireless" else _ENDPOINT_WIRED
    values = [max(0, min(15, v)) for v in (left_stick, right_stick, left_trigger, right_trigger)]
    try:
        fd = os.open(hidraw_path, os.O_RDWR)
    except OSError as e:
        log.warning("Analog deadzone setup failed (open %s): %s", hidraw_path, e)
        return
    try:
        for i, val in enumerate(values):
            os.write(fd, _packet(endpoint, RGB_CMD_INIT_WRITE + _DZ_INIT[i]))
            _read(fd, 0.1)
            os.write(fd, _packet(endpoint, RGB_CMD_INIT_WRITE + _DZ_MIN[i] + bytes([val])))
            _read(fd, 0.1)
            os.write(fd, _packet(endpoint, RGB_CMD_INIT_WRITE + _DZ_MAX[i] + bytes([val])))
            _read(fd, 0.1)
        log.info("HW deadzones: sticks L=%d R=%d triggers L=%d R=%d", *values)
    except OSError as e:
        log.warning("Analog deadzone setup failed (write): %s", e)
    finally:
        os.close(fd)


class ControlReader:
    """Reads all input from the SCUF control HID interface (hidraw, interface 0).

    Handles buttons (data[2]==0x02), triggers/L2/R2 (data[2]==0x0a), and battery
    polling. Sends software-mode init, keepalives every 20s, and battery queries
    every 60s using OLH's 64-byte packet framing.
    """

    def __init__(self, hidraw_path: str, connection_type: str = "wired",
                 notify_thresholds: list[int] | None = None):
        self._path = hidraw_path
        self._endpoint = _ENDPOINT_WIRELESS if connection_type == "wireless" else _ENDPOINT_WIRED
        self._level = -1
        self._fd = None
        self._thread = None
        # Sorted descending so we can find the highest crossed threshold easily
        self._thresholds: list[int] = sorted(notify_thresholds or [], reverse=True)
        self._notified: set[int] = set()
        self._prev_level = -1
        self._connect_time: float = 0.0
        self._stable: bool = False
        self._btn_state: dict[int, bool] = {}
        self._dpad_state: dict[int, int] = {ecodes.ABS_HAT0X: 0, ecodes.ABS_HAT0Y: 0}
        self._button_cb = None
        self._axis_cb = None
        self._syn_cb = None

    def set_input_callbacks(self, button_cb, axis_cb, syn_cb=None) -> None:
        self._button_cb = button_cb
        self._axis_cb = axis_cb
        self._syn_cb = syn_cb
        # Clear any stale state accumulated during RGB init (ack packets can
        # spuriously set paddle/SAX bits, causing missed first-press events).
        self._btn_state.clear()
        self._dpad_state[ecodes.ABS_HAT0X] = 0
        self._dpad_state[ecodes.ABS_HAT0Y] = 0

    @property
    def level(self) -> int:
        """Current battery percentage (0-100), or -1 if not yet known."""
        return self._level

    def start(self):
        """Open hidraw, init software mode, request battery, start read loop."""
        self._fd = os.open(self._path, os.O_RDWR)
        self._connect_time = time.monotonic()
        self._stable = False

        # Required before battery or any other query (OLH step 2 in Connect())
        os.write(self._fd, _packet(self._endpoint, _CMD_SOFTWARE_MODE))
        _read(self._fd, 1.0)  # consume ack

        # Queue initial battery query; _read_loop handles the response
        os.write(self._fd, _packet(self._endpoint, _CMD_BATTERY))

        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="battery-reader"
        )
        self._thread.start()

    def _parse_battery(self, data: bytes) -> None:
        """Try both response formats and log if a valid level is found."""
        val = 0
        # Unsolicited dongle report: data[0]==0x03, data[2]==0x01, data[3]==0x0f
        if (len(data) >= 7
                and data[0] == 0x03
                and data[2] == 0x01
                and data[3] == 0x0f):
            val = struct.unpack_from('<H', data, 5)[0] // 10
        # Direct query response: data[3] must echo the battery command byte (0x0f)
        # to reject unrelated HID reports (button presses, etc.) that share the fd.
        elif len(data) >= 6 and data[3] == 0x0f:
            candidate = struct.unpack_from('<H', data, 4)[0] // 10
            if 0 < candidate <= 100:
                val = candidate

        if val > 0:
            warmup = not self._stable and (time.monotonic() - self._connect_time) < _WARMUP_SECS
            if val != self._level:
                self._level = val
                log.info("Battery update%s: %d%%", " (warmup)" if warmup else "", val)
            else:
                log.info("Battery poll: %d%% (unchanged)", val)
            self._check_thresholds(val, suppress=warmup)

    def _check_thresholds(self, level: int, suppress: bool = False) -> None:
        """Fire a notification when crossing a threshold downward.

        During the BMS warmup window (suppress=True), thresholds are tracked but
        not fired — the BMS SoC estimate is unreliable for ~90s after connect.
        On the first non-suppressed call, fires for any threshold already breached.
        On subsequent reads, fires only at the moment of crossing
        (prev > threshold >= current). Resets silently on recovery.
        """
        first_stable = not self._stable and not suppress
        if first_stable:
            self._stable = True

        # prev_level for crossing logic: treat first stable reading like "first ever"
        # so we catch any threshold the battery has already dipped below
        effective_prev = -1 if first_stable else self._prev_level

        newly_breached = []
        for t in self._thresholds:
            if level > t:
                self._notified.discard(t)
            elif not suppress and t not in self._notified and (effective_prev < 0 or effective_prev > t):
                self._notified.add(t)
                newly_breached.append(t)

        if newly_breached:
            t = min(newly_breached)  # most severe threshold only
            if t == 1:
                body = f"Battery below {t}% ({level}%) — controller will shut off soon!"
            elif t <= 5:
                body = f"Battery below {t}% ({level}%) — plug in soon."
            else:
                body = f"Battery below {t}% (currently {level}%)."
            log.info("Low battery notification: %d%% (threshold %d%%)", level, t)
            threading.Thread(
                target=_notify,
                args=("SCUF Controller Battery Low", body, "normal"),
                daemon=True,
            ).start()
        self._prev_level = level

    def _read_loop(self):
        now = time.monotonic()
        next_keepalive = now + _KEEPALIVE_INTERVAL
        next_battery   = now + _BATTERY_INTERVAL

        while self._fd is not None:
            now = time.monotonic()
            timeout = min(next_keepalive - now, next_battery - now)

            r, _, _ = select.select([self._fd], [], [], max(0.1, timeout))

            if r:
                try:
                    data = os.read(self._fd, _REPORT_SIZE)
                except OSError:
                    break
                self._parse_battery(data)
                self._parse_buttons(data)
                self._parse_triggers(data)

            now = time.monotonic()
            if now >= next_keepalive:
                try:
                    os.write(self._fd, _packet(self._endpoint, _CMD_KEEPALIVE))
                    log.debug("Battery keepalive sent")
                except OSError:
                    pass  # controller temporarily unreachable; keep looping until read fails
                next_keepalive = now + _KEEPALIVE_INTERVAL

            if now >= next_battery:
                try:
                    os.write(self._fd, _packet(self._endpoint, _CMD_BATTERY))
                    log.info("Battery poll sent")
                except OSError:
                    pass  # same — skip this poll, retry next interval
                next_battery = now + _BATTERY_INTERVAL

    def _parse_buttons(self, data: bytes) -> None:
        if len(data) < 7 or data[0] != 0x03 or data[2] != 0x02:
            return
        mask = int.from_bytes(data[HID_BTN_MASK_OFFSET:HID_BTN_MASK_OFFSET + 4], 'little')
        log.debug("BTN PKT d1=0x%02x mask=0x%08x raw=%s", data[1], mask, data[:8].hex())
        changed = False
        for bit, code in HID_BUTTON_MAP.items():
            state = bool(mask & bit)
            if state != self._btn_state.get(code, False):
                self._btn_state[code] = state
                log.debug("  state change bit=0x%06x code=%d val=%d cb=%s",
                          bit, code, int(state), "set" if self._button_cb else "NONE")
                if self._button_cb:
                    self._button_cb(code, int(state))
                changed = True
        hat_x = sum(d for bit, ax, d in HID_DPAD if ax == ecodes.ABS_HAT0X and (mask & bit))
        hat_y = sum(d for bit, ax, d in HID_DPAD if ax == ecodes.ABS_HAT0Y and (mask & bit))
        for axis, val in ((ecodes.ABS_HAT0X, hat_x), (ecodes.ABS_HAT0Y, hat_y)):
            if val != self._dpad_state[axis]:
                self._dpad_state[axis] = val
                if self._axis_cb:
                    self._axis_cb(axis, val)
                changed = True
        if changed and self._syn_cb:
            self._syn_cb()

    def _parse_triggers(self, data: bytes) -> None:
        if len(data) < 8 or data[0] != 0x03 or data[2] != 0x0a:
            return
        left  = int.from_bytes(data[4:6], 'little')
        right = int.from_bytes(data[6:8], 'little')
        if self._axis_cb:
            self._axis_cb(ecodes.ABS_Z,  left)
            self._axis_cb(ecodes.ABS_RZ, right)
        if self._syn_cb:
            self._syn_cb()

    def close(self):
        """Close the hidraw fd, which unblocks the read loop."""
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class AnalogListener:
    """Reads analog stick data from USB interface 3 (the dedicated analog HID endpoint).

    Fires axis callbacks for left stick (ABS_X/ABS_Y) and right stick (ABS_RX/ABS_RY)
    with raw int16 values in the range -32768..32767. Packet format matches OLH's
    analogDataListener: bytes 1-4 = left stick, bytes 5-8 = right stick, each as two
    little-endian signed 16-bit values.
    """

    def __init__(self, hidraw_path: str, axis_cb, syn_cb=None):
        self._path = hidraw_path
        self._axis_cb = axis_cb
        self._syn_cb = syn_cb
        self._fd = None
        self._thread = None

    def start(self) -> None:
        self._fd = os.open(self._path, os.O_RDONLY)
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="analog-listener")
        self._thread.start()

    def _read_loop(self) -> None:
        while self._fd is not None:
            r, _, _ = select.select([self._fd], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(self._fd, _REPORT_SIZE)
            except OSError:
                break
            if len(data) < 9:
                continue
            lx = int.from_bytes(data[1:3], 'little', signed=True)
            ly = int.from_bytes(data[3:5], 'little', signed=True)
            rx = int.from_bytes(data[5:7], 'little', signed=True)
            ry = int.from_bytes(data[7:9], 'little', signed=True)
            if self._axis_cb:
                self._axis_cb(ecodes.ABS_X,  lx)
                self._axis_cb(ecodes.ABS_Y,  ly)
                self._axis_cb(ecodes.ABS_RX, rx)
                self._axis_cb(ecodes.ABS_RY, ry)
            if self._syn_cb:
                self._syn_cb()

    def close(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class RGBController:
    """Controls the LED strip on the SCUF Envision Pro V2 via HID raw interface.

    On init: sends software mode + opens LED endpoint.
    set_color() writes a single 27-byte color packet (all 9 LEDs same color).
    """

    def __init__(self, hidraw_path: str, connection_type: str = "wired"):
        self._path = hidraw_path
        self._endpoint = _ENDPOINT_WIRELESS if connection_type == "wireless" else _ENDPOINT_WIRED
        self._fd: int | None = None
        self._open()

    def _open(self):
        try:
            self._fd = os.open(self._path, os.O_RDWR)
            # OLH Connect() sequence: software mode → open LED endpoint →
            # activate trigger backend → disable eco mode (once, at init)
            os.write(self._fd, _packet(self._endpoint, _CMD_SOFTWARE_MODE))
            _read(self._fd, 1.0)
            os.write(self._fd, _packet(self._endpoint, RGB_CMD_OPEN_ENDPOINT))
            _read(self._fd, 0.5)
            os.write(self._fd, _packet(self._endpoint, RGB_CMD_INIT_WRITE + RGB_CMD_TRIGGER_BACKEND))
            _read(self._fd, 0.5)
            os.write(self._fd, _packet(self._endpoint, RGB_CMD_INIT_WRITE + RGB_CMD_ECO_MODE_OFF))
            log.info("RGB controller initialized: %s", self._path)
        except OSError as e:
            log.error("RGB init failed on %s: %s", self._path, e)
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def write_frame(self, buf: bytes) -> None:
        """Send a raw 27-byte planar RGB frame (R×9, G×9, B×9)."""
        if self._fd is None:
            return
        length = len(buf)
        cmd = RGB_CMD_WRITE_COLOR + bytes([length & 0xff, length >> 8, 0x00, 0x00]) + buf
        try:
            os.write(self._fd, _packet(self._endpoint, cmd))
        except OSError as e:
            log.warning("RGB frame write failed: %s", e)

    def set_color(self, r: int, g: int, b: int, brightness: int = 100) -> None:
        """Set all LEDs to one color. r/g/b in 0-255, brightness in 0-100."""
        scale = brightness / 100.0
        ri, gi, bi = int(r * scale), int(g * scale), int(b * scale)
        self.write_frame(bytes([ri] * RGB_NUM_LEDS + [gi] * RGB_NUM_LEDS + [bi] * RGB_NUM_LEDS))
        log.debug("RGB (%d,%d,%d) @ %d%%", ri, gi, bi, brightness)

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
