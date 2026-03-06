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
    AXIS_INFO, BUTTON_MAP, PADDLE_MAP, FF_MAX_EFFECTS,
)

log = logging.getLogger(__name__)


class VirtualGamepad:
    """uinput virtual Xbox gamepad."""

    def __init__(self):
        self._device = None
        self._rumble_enabled = False

    def create(self, rumble: bool = False):
        """Create the virtual gamepad device.

        Args:
            rumble: If True, advertise FF_RUMBLE capability so games can
                    send force-feedback events.
        """
        self._rumble_enabled = rumble

        # Define capabilities: all standard Xbox buttons + paddles
        all_buttons = sorted(set(BUTTON_MAP.values()) | set(PADDLE_MAP.values()))

        # Axes with their AbsInfo
        all_axes = [(code, info) for code, info in AXIS_INFO.items()]

        capabilities = {
            ecodes.EV_KEY: all_buttons,
            ecodes.EV_ABS: all_axes,
        }

        ff_effects_max = 0
        if rumble:
            capabilities[ecodes.EV_FF] = [ecodes.FF_RUMBLE, ecodes.FF_GAIN]
            ff_effects_max = FF_MAX_EFFECTS

        self._device = UInput(
            events=capabilities,
            name=VIRTUAL_DEVICE_NAME,
            vendor=VIRTUAL_VENDOR,
            product=VIRTUAL_PRODUCT,
            version=VIRTUAL_VERSION,
            max_effects=ff_effects_max,
        )

        log.info(f"Created virtual gamepad: {self._device.device.path}"
                 f"{' (rumble enabled)' if rumble else ''}")

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
    def fd(self) -> int:
        """File descriptor of the uinput device (for polling FF events)."""
        if self._device:
            return self._device.fd
        return -1

    @property
    def uinput(self):
        """The underlying UInput object (for begin_upload / end_upload etc.)."""
        return self._device

    @property
    def device_path(self) -> str:
        if self._device:
            return self._device.device.path
        return ""
