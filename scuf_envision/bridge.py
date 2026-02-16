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
import time

import evdev
from evdev import ecodes

from .constants import (
    BUTTON_MAP, PADDLE_MAP, AXIS_MAP, POLL_TIMEOUT_MS,
)
from .discovery import DiscoveredDevice, discover_scuf, discover_scuf_with_retry
from .input_filter import InputFilter
from .virtual_gamepad import VirtualGamepad

log = logging.getLogger(__name__)


class _DeviceDisconnected(Exception):
    """Raised when the physical device is lost."""
    pass


class BridgeService:
    """Bridges the physical SCUF controller to a virtual Xbox gamepad."""

    def __init__(self, discovered: DiscoveredDevice, filter_config: dict = None,
                 reconnect: bool = False):
        self.discovered = discovered
        self.filter = InputFilter(**(filter_config or {}))
        self.gamepad = VirtualGamepad()
        self._reconnect = reconnect

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

        self._running = True
        try:
            self.gamepad.create()
            self._open_devices()
            log.info("Bridge started - SCUF -> Xbox translation active")
            self._run_with_reconnect()
        finally:
            self._cleanup()

    def _run_with_reconnect(self):
        """Run the event loop, with optional reconnection on disconnect."""
        while self._running:
            try:
                self._event_loop()
                break  # Clean exit from event loop (shutdown requested)
            except _DeviceDisconnected:
                self._release_physical()
                if not self._reconnect or not self._running:
                    break
                log.info("Controller disconnected. Waiting for reconnection...")
                self._zero_virtual_outputs()
                if not self._wait_for_reconnect():
                    break
                log.info("Controller reconnected!")

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
                    raise _DeviceDisconnected() from e

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

    def _release_physical(self):
        """Release physical devices only, keeping the virtual gamepad alive."""
        for dev in self._grabbed_devices:
            try:
                dev.ungrab()
                dev.close()
            except OSError:
                pass
        self._grabbed_devices.clear()
        self._physical = None

    def _zero_virtual_outputs(self):
        """Zero all stick/trigger axes to prevent stuck inputs on disconnect."""
        for axis in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY,
                     ecodes.ABS_Z, ecodes.ABS_RZ):
            self.gamepad.emit_axis(axis, 0)
        self.gamepad.syn()
        self._raw_left_x = self._raw_left_y = 0
        self._raw_right_x = self._raw_right_y = 0

    def _wait_for_reconnect(self, poll_interval: float = 2.0,
                             max_wait: float = 300.0) -> bool:
        """Poll for the controller to reappear. Returns True if reconnected."""
        waited = 0.0
        while self._running and waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            discovered = discover_scuf()
            if discovered is not None:
                self.discovered = discovered
                try:
                    self._open_devices()
                    # Re-apply audio config on reconnection
                    from .audio_control import apply_audio_config
                    try:
                        apply_audio_config()
                    except Exception:
                        pass
                    return True
                except OSError as e:
                    log.warning(f"Device found but failed to open: {e}")
                    continue
        if waited >= max_wait:
            log.warning(f"Reconnection timeout ({max_wait:.0f}s), giving up.")
        return False

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM gracefully."""
        log.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def _cleanup(self):
        """Release all grabbed devices and destroy the virtual gamepad."""
        log.info("Cleaning up...")
        self._release_physical()
        self.gamepad.close()
        log.info("Cleanup complete")


def run():
    """Entry point: discover device and run the bridge."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from . import __version__
    log.info(f"SCUF Envision Pro V2 Linux Driver v{__version__} starting...")

    discovered = discover_scuf_with_retry()
    if discovered is None:
        log.error("No SCUF Envision Pro V2 controller found after 30s!")
        log.error("Make sure the controller is plugged in via USB or wireless receiver is connected.")
        log.error("Check: lsusb | grep 1b1c")
        sys.exit(1)

    log.info(f"Found controller: {discovered}")

    # Apply audio config (disable/enable USB audio per /etc/scuf-envision/config.ini)
    from .audio_control import apply_audio_config
    try:
        apply_audio_config()
    except Exception as e:
        log.warning(f"Could not apply audio config: {e}")

    # Enable reconnection for wireless connections
    reconnect = (discovered.connection_type == "wireless")
    if reconnect:
        log.info("Wireless mode: reconnection on disconnect is enabled")

    bridge = BridgeService(discovered, reconnect=reconnect)
    bridge.start()
