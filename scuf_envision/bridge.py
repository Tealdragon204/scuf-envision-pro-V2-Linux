"""
Main bridge service: reads from physical SCUF, remaps, writes to virtual Xbox gamepad.

This is the core event loop that:
1. Opens the physical SCUF evdev device with exclusive grab
2. Reads input events at ~250 Hz
3. Translates non-standard SCUF codes to standard Xbox codes
4. Applies deadzone and jitter filtering
5. Writes to the virtual uinput gamepad
"""

import logging
import select
import signal
import sys

import evdev
from evdev import ecodes

from .constants import (
    BUTTON_MAP, PADDLE_MAP, AXIS_MAP, POLL_TIMEOUT_MS,
)
from .discovery import DiscoveredDevice, discover_scuf
from .input_filter import InputFilter
from .virtual_gamepad import VirtualGamepad

log = logging.getLogger(__name__)


class BridgeService:
    """Bridges the physical SCUF controller to a virtual Xbox gamepad."""

    def __init__(self, discovered: DiscoveredDevice, filter_config: dict = None):
        self.discovered = discovered
        self.filter = InputFilter(**(filter_config or {}))
        self.gamepad = VirtualGamepad()

        self._physical = None
        self._grabbed_devices = []
        self._running = False

        # Raw stick state for radial deadzone (need both X/Y together)
        self._raw_left_x = 0
        self._raw_left_y = 0
        self._raw_right_x = 0
        self._raw_right_y = 0

    def start(self):
        """Open devices and start the event loop."""
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self._open_devices()
            self.gamepad.create()
            self._running = True
            log.info("Bridge started - SCUF -> Xbox translation active")
            self._event_loop()
        finally:
            self._cleanup()

    def _open_devices(self):
        """Open the physical controller and grab it exclusively."""
        log.info(f"Opening physical device: {self.discovered.event_path}")
        self._physical = evdev.InputDevice(self.discovered.event_path)

        # Exclusive grab prevents double input (raw + virtual)
        self._physical.grab()
        self._grabbed_devices.append(self._physical)
        log.info(f"Exclusively grabbed: {self._physical.name}")

        # Also grab secondary devices to suppress their input leakage
        for sec_path in self.discovered.secondary_event_paths:
            try:
                sec_dev = evdev.InputDevice(sec_path)
                sec_dev.grab()
                self._grabbed_devices.append(sec_dev)
                log.debug(f"Grabbed secondary: {sec_path}")
            except (OSError, PermissionError) as e:
                log.warning(f"Could not grab secondary device {sec_path}: {e}")

    def _event_loop(self):
        """Main polling loop at ~250 Hz."""
        fd = self._physical.fd
        poll = select.poll()
        poll.register(fd, select.POLLIN)

        while self._running:
            events = poll.poll(POLL_TIMEOUT_MS)
            if not events:
                continue

            try:
                for event in self._physical.read():
                    self._handle_event(event)
            except OSError as e:
                if self._running:
                    log.error(f"Device read error: {e}")
                    log.info("Controller may have disconnected")
                    self._running = False

    def _handle_event(self, event):
        """Process a single evdev event from the physical controller."""
        if event.type == ecodes.EV_KEY:
            self._handle_button(event)
        elif event.type == ecodes.EV_ABS:
            self._handle_axis(event)
        elif event.type == ecodes.EV_SYN:
            self.gamepad.syn()

    def _handle_button(self, event):
        """Remap and forward a button event."""
        code = event.code

        # Check main button map
        if code in BUTTON_MAP:
            mapped = BUTTON_MAP[code]
            self.gamepad.emit_button(mapped, event.value)
            self.gamepad.syn()
            return

        # Check paddle map
        if code in PADDLE_MAP:
            mapped = PADDLE_MAP[code]
            self.gamepad.emit_button(mapped, event.value)
            self.gamepad.syn()
            return

        # Unknown button - log it for debugging
        if event.value == 1:  # Only log presses, not releases
            log.debug(f"Unknown button: code=0x{code:03x} ({code}) value={event.value}")

    def _handle_axis(self, event):
        """Remap and forward an axis event with filtering."""
        code = event.code
        value = event.value

        if code not in AXIS_MAP:
            return

        mapped = AXIS_MAP[code]

        # Track raw stick values for radial deadzone
        if code == ecodes.ABS_X:
            self._raw_left_x = value
            self._emit_filtered_stick("left", self._raw_left_x, self._raw_left_y,
                                       ecodes.ABS_X, ecodes.ABS_Y)
            return
        elif code == ecodes.ABS_Y:
            self._raw_left_y = value
            self._emit_filtered_stick("left", self._raw_left_x, self._raw_left_y,
                                       ecodes.ABS_X, ecodes.ABS_Y)
            return
        elif code == ecodes.ABS_Z:
            # SCUF ABS_Z -> Right Stick X
            self._raw_right_x = value
            self._emit_filtered_stick("right", self._raw_right_x, self._raw_right_y,
                                       ecodes.ABS_RX, ecodes.ABS_RY)
            return
        elif code == ecodes.ABS_RZ:
            # SCUF ABS_RZ -> Right Stick Y
            self._raw_right_y = value
            self._emit_filtered_stick("right", self._raw_right_x, self._raw_right_y,
                                       ecodes.ABS_RX, ecodes.ABS_RY)
            return
        elif code == ecodes.ABS_RX:
            # SCUF ABS_RX -> Left Trigger
            filtered = self.filter.filter_trigger(value)
            filtered, changed = self.filter.suppress_jitter("lt", filtered)
            if changed:
                self.gamepad.emit_axis(ecodes.ABS_Z, filtered)
                self.gamepad.syn()
            return
        elif code == ecodes.ABS_RY:
            # SCUF ABS_RY -> Right Trigger
            filtered = self.filter.filter_trigger(value)
            filtered, changed = self.filter.suppress_jitter("rt", filtered)
            if changed:
                self.gamepad.emit_axis(ecodes.ABS_RZ, filtered)
                self.gamepad.syn()
            return

        # D-pad and anything else: pass through mapped
        self.gamepad.emit_axis(mapped, value)
        self.gamepad.syn()

    def _emit_filtered_stick(self, stick_name: str, raw_x: int, raw_y: int,
                              out_x_code: int, out_y_code: int):
        """Apply radial deadzone and emit filtered stick values."""
        fx, fy = self.filter.filter_stick(raw_x, raw_y)

        fx, x_changed = self.filter.suppress_jitter(f"{stick_name}_x", fx)
        fy, y_changed = self.filter.suppress_jitter(f"{stick_name}_y", fy)

        if x_changed or y_changed:
            self.gamepad.emit_axis(out_x_code, fx)
            self.gamepad.emit_axis(out_y_code, fy)
            self.gamepad.syn()

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM gracefully."""
        log.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def _cleanup(self):
        """Release all grabbed devices and destroy the virtual gamepad."""
        log.info("Cleaning up...")
        for dev in self._grabbed_devices:
            try:
                dev.ungrab()
                dev.close()
                log.debug(f"Released: {dev.path}")
            except OSError:
                pass
        self._grabbed_devices.clear()
        self.gamepad.close()
        log.info("Cleanup complete")


def run():
    """Entry point: discover device and run the bridge."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("SCUF Envision Pro V2 Linux Driver starting...")

    discovered = discover_scuf()
    if discovered is None:
        log.error("No SCUF Envision Pro V2 controller found!")
        log.error("Make sure the controller is plugged in via USB.")
        log.error("Check: lsusb | grep 1b1c")
        sys.exit(1)

    log.info(f"Found controller: {discovered}")

    bridge = BridgeService(discovered)
    bridge.start()
