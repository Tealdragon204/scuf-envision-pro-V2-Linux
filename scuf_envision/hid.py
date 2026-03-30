"""
HID raw interface for the SCUF Envision Pro V2.

Phase 9: Battery level reading via the control HID interface.
"""

import os
import select
import struct
import threading
import time
import logging

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


class BatteryReader:
    """Reads battery level from the SCUF control HID interface.

    Sends software-mode then battery-query with OLH's 64-byte packet framing.
    The read loop uses select with a short timeout so it can send keepalives
    every 20s (matching OLH's heartbeat) and re-poll battery every 60s without
    blocking shutdown. Battery updates arrive either as direct query responses
    (wired, bytes [4:6]) or as unsolicited dongle reports (wireless, bytes [5:7],
    signature data[0]==0x03, data[2]==0x01, data[3]==0x0f).
    """

    def __init__(self, hidraw_path: str, connection_type: str = "wired"):
        self._path = hidraw_path
        self._endpoint = _ENDPOINT_WIRELESS if connection_type == "wireless" else _ENDPOINT_WIRED
        self._level = -1
        self._fd = None
        self._thread = None

    @property
    def level(self) -> int:
        """Current battery percentage (0-100), or -1 if not yet known."""
        return self._level

    def start(self):
        """Open hidraw, init software mode, request battery, start read loop."""
        self._fd = os.open(self._path, os.O_RDWR)

        # Required before battery or any other query (OLH step 2 in Connect())
        os.write(self._fd, _packet(self._endpoint, _CMD_SOFTWARE_MODE))
        _read(self._fd, 1.0)  # consume ack

        # Initial battery query
        os.write(self._fd, _packet(self._endpoint, _CMD_BATTERY))
        data = _read(self._fd, 1.0)
        if len(data) >= 6:
            val = struct.unpack_from('<H', data, 4)[0] // 10
            if val > 0:
                self._level = val
                log.info("Battery level: %d%%", val)

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
        # Direct query response: battery at [4:6]
        elif len(data) >= 6:
            candidate = struct.unpack_from('<H', data, 4)[0] // 10
            if 0 < candidate <= 100:
                val = candidate

        if val > 0:
            if val != self._level:
                self._level = val
                log.info("Battery update: %d%%", val)
            else:
                log.debug("Battery poll: %d%% (unchanged)", val)

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

            now = time.monotonic()
            if now >= next_keepalive:
                try:
                    os.write(self._fd, _packet(self._endpoint, _CMD_KEEPALIVE))
                except OSError:
                    break
                log.debug("Battery keepalive sent")
                next_keepalive = now + _KEEPALIVE_INTERVAL

            if now >= next_battery:
                try:
                    os.write(self._fd, _packet(self._endpoint, _CMD_BATTERY))
                except OSError:
                    break
                log.info("Battery poll sent")
                next_battery = now + _BATTERY_INTERVAL

    def close(self):
        """Close the hidraw fd, which unblocks the read loop."""
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
