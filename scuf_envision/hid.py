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

_CMD_BATTERY = bytes([0x02, 0x0f])
_REPORT_SIZE = 64


class BatteryReader:
    """Reads battery level from the SCUF control HID interface.

    Sends [0x02, 0x0f] on start to get the current level (bytes [4:6]
    as LE uint16 / 10). Then loops reading reports; updates on packets
    where data[0]==0x03, data[2]==0x01, data[3]==0x0f (bytes [5:7]).
    Runs the read loop in a daemon thread so it doesn't block shutdown.
    """

    def __init__(self, hidraw_path: str):
        self._path = hidraw_path
        self._level = -1
        self._fd = None
        self._thread = None

    @property
    def level(self) -> int:
        """Current battery percentage (0-100), or -1 if not yet known."""
        return self._level

    def start(self):
        """Open hidraw, read initial level, and start the background read loop."""
        self._fd = os.open(self._path, os.O_RDWR)
        os.write(self._fd, _CMD_BATTERY)
        ready, _, _ = select.select([self._fd], [], [], 0.5)
        if ready:
            data = os.read(self._fd, _REPORT_SIZE)
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
