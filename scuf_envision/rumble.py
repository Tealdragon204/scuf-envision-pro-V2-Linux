"""
Rumble (force-feedback) handler for the SCUF Envision Pro V2.

Translates Linux FF_RUMBLE effects into the 13-byte HID output report
that drives the controller's left (strong) and right (weak) vibration motors.

Protocol confirmed via OpenLinkHub (Go) and Wireshark USB capture on Windows.
"""

import logging
import os

from .constants import (
    RUMBLE_REPORT, RUMBLE_LEFT_OFFSET, RUMBLE_RIGHT_OFFSET,
    VIBRATION_LEFT_CMD, VIBRATION_RIGHT_CMD, VIBRATION_MAX_INTENSITY,
    VIBRATION_TRANSFER_HEADER, VIBRATION_TRANSFER_SIZE,
)

log = logging.getLogger(__name__)


class RumbleHandler:
    """Opens the SCUF's hidraw device and writes rumble packets."""

    def __init__(self, hidraw_path: str):
        self._path = hidraw_path
        self._fd = None
        self._open()

    def _open(self):
        try:
            self._fd = os.open(self._path, os.O_WRONLY | os.O_NONBLOCK)
            log.info("Opened hidraw for rumble: %s", self._path)
        except OSError as e:
            log.error("Failed to open hidraw %s for rumble: %s", self._path, e)
            self._fd = None

    def set_motors(self, strong: int, weak: int):
        """Send a rumble command.

        Args:
            strong: Left (strong) motor magnitude, 0-65535 (evdev FF scale).
            weak:   Right (weak) motor magnitude, 0-65535 (evdev FF scale).
        """
        if self._fd is None:
            return

        # Scale from evdev 0-65535 to HID 0-255
        left = min(255, strong >> 8)
        right = min(255, weak >> 8)

        buf = bytearray(RUMBLE_REPORT)
        buf[RUMBLE_LEFT_OFFSET] = left
        buf[RUMBLE_RIGHT_OFFSET] = right

        log.debug("HID rumble: left=%d/255 right=%d/255 pkt=%s",
                   left, right, buf.hex())
        try:
            os.write(self._fd, bytes(buf))
        except OSError as e:
            log.warning("Rumble write failed: %s", e)

    def stop(self):
        """Stop both motors."""
        self.set_motors(0, 0)

    def close(self):
        """Stop motors and close the hidraw device."""
        if self._fd is not None:
            try:
                self.stop()
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            log.info("Closed hidraw rumble device")


def init_vibration_modules(control_hidraw_path: str):
    """Set both vibration motors to max hardware intensity (100%).

    Sends the 0x84 (left) and 0x85 (right) commands via the control
    hidraw device. This is equivalent to iCUE's vibration intensity
    slider on Windows. Without this, the controller may use a stale
    lower intensity from a previous configuration session.

    Args:
        control_hidraw_path: Path to the control hidraw device (not interface 3).
    """
    try:
        fd = os.open(control_hidraw_path, os.O_RDWR)
    except OSError as e:
        log.warning("Failed to open control hidraw %s: %s", control_hidraw_path, e)
        return

    try:
        for cmd in (VIBRATION_LEFT_CMD, VIBRATION_RIGHT_CMD):
            buf = bytearray(VIBRATION_TRANSFER_SIZE)
            buf[:len(VIBRATION_TRANSFER_HEADER)] = VIBRATION_TRANSFER_HEADER
            buf[len(VIBRATION_TRANSFER_HEADER)] = cmd
            buf[len(VIBRATION_TRANSFER_HEADER) + 1] = 0x00
            buf[len(VIBRATION_TRANSFER_HEADER) + 2] = VIBRATION_MAX_INTENSITY
            try:
                os.write(fd, bytes(buf))
                os.read(fd, 64)
            except OSError as e:
                log.warning("Vibration module init cmd 0x%02x failed: %s", cmd, e)
        log.info("Vibration modules set to %d%% intensity (hidraw: %s)",
                 VIBRATION_MAX_INTENSITY, control_hidraw_path)
    finally:
        os.close(fd)
