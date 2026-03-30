"""
HID raw interface for the SCUF Envision Pro V2.

Phase 9: Battery level reading via the control HID interface.
"""

import os
import select
import struct
import threading
import logging

log = logging.getLogger(__name__)

_REPORT_SIZE = 64
_CMD_SOFTWARE_MODE = bytes([0x01, 0x03, 0x00, 0x02])
_CMD_BATTERY      = bytes([0x02, 0x0f])

# Endpoint byte differs by connection type (OLH: 0x08 wired, 0x09 wireless dongle)
_ENDPOINT_WIRED    = 0x08
_ENDPOINT_WIRELESS = 0x09


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

    Sends software-mode then battery-query commands using OLH's 64-byte
    packet framing. For the wireless dongle the initial response may not
    carry battery data; the background thread catches unsolicited reports
    matching data[0]==0x03, data[2]==0x01, data[3]==0x0f (bytes [5:7]).
    For wired, the direct response to the battery query carries it at [4:6].
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

        # Initial battery query; wireless dongle may not respond here directly
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

    def _read_loop(self):
        while self._fd is not None:
            try:
                data = os.read(self._fd, _REPORT_SIZE)
            except OSError:
                break
            if (len(data) >= 7
                    and data[0] == 0x03
                    and data[2] == 0x01
                    and data[3] == 0x0f):
                val = struct.unpack_from('<H', data, 5)[0] // 10
                if val > 0 and val != self._level:
                    self._level = val
                    log.info("Battery update: %d%%", val)

    def close(self):
        """Close the hidraw fd, which unblocks the read loop."""
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
