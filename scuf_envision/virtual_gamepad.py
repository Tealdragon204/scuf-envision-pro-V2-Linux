"""
Virtual Xbox gamepad via Linux uinput.

Creates a virtual input device that presents as a standard Xbox controller.
Games and Steam see this as a normal Xbox gamepad with correct button mappings.
"""

import logging
import evdev
from evdev import ecodes, UInput

from .constants import (
    VIRTUAL_DEVICE_NAME, VIRTUAL_VENDOR, VIRTUAL_PRODUCT, VIRTUAL_VERSION,
    AXIS_INFO, BUTTON_MAP, PADDLE_MAP,
)

log = logging.getLogger(__name__)


class VirtualGamepad:
    """uinput virtual Xbox gamepad."""

    def __init__(self):
        self._device = None

    def create(self):
        """Create the virtual gamepad device."""
        # Define capabilities: all standard Xbox buttons + paddles
        all_buttons = sorted(set(BUTTON_MAP.values()) | set(PADDLE_MAP.values()))

        # Axes with their AbsInfo
        all_axes = [(code, info) for code, info in AXIS_INFO.items()]

        capabilities = {
            ecodes.EV_KEY: all_buttons,
            ecodes.EV_ABS: all_axes,
        }

        self._device = UInput(
            events=capabilities,
            name=VIRTUAL_DEVICE_NAME,
            vendor=VIRTUAL_VENDOR,
            product=VIRTUAL_PRODUCT,
            version=VIRTUAL_VERSION,
        )

        log.info(f"Created virtual gamepad: {self._device.device.path}")

    def emit_button(self, code: int, value: int):
        """Emit a button press/release event."""
        if self._device:
            self._device.write(ecodes.EV_KEY, code, value)

    def emit_axis(self, code: int, value: int):
        """Emit an axis value change."""
        if self._device:
            self._device.write(ecodes.EV_ABS, code, value)

    def syn(self):
        """Send a SYN_REPORT to flush pending events."""
        if self._device:
            self._device.syn()

    def close(self):
        """Destroy the virtual device."""
        if self._device:
            log.info("Destroying virtual gamepad")
            self._device.close()
            self._device = None

    @property
    def device_path(self) -> str:
        if self._device:
            return self._device.device.path
        return ""
