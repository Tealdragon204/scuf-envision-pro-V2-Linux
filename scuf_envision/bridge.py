"""
Main bridge service: reads from physical SCUF, remaps, writes to virtual Xbox gamepad.

This is the core event loop that:
1. Opens the physical SCUF evdev device with exclusive grab
2. Reads input events at ~500 Hz
3. Translates non-standard SCUF codes to standard Xbox codes via the active profile
4. Applies deadzone and jitter filtering
5. Writes to the virtual uinput gamepad

Profile switching and driver status are available at runtime via the IPC socket
at /run/scuf-envision/ipc.sock (see ipc.py, tools/scuf-ctl).
"""

import logging
import os
import select
import signal
import sys
import time

import evdev
from evdev import ecodes

from .config import load_config, poll_timeout_ms as _poll_timeout_ms
from .discovery import DiscoveredDevice, discover_scuf, find_competing_gamepads
from .input_filter import InputFilter
from .ipc import IPCServer
from .profile import ProfileManager
from .virtual_gamepad import VirtualGamepad

log = logging.getLogger(__name__)


class _DeviceDisconnected(Exception):
    pass


class BridgeService:
    """Bridges the physical SCUF controller to a virtual Xbox gamepad."""

    def __init__(self, discovered: DiscoveredDevice, filter_config: dict = None,
                 reconnect: bool = False, rumble_enabled: bool = False,
                 initial_profile: str | None = None, ipc_server=None):
        self.discovered = discovered
        self.filter = InputFilter(**(filter_config or {}))
        self.gamepad = VirtualGamepad()
        self._reconnect = reconnect
        self._rumble_enabled = rumble_enabled
        self._initial_profile = initial_profile
        self._rumble = None
        self._ff_effects = {}
        self._ff_gain = 65535

        self._control = None
        self._analog = None
        self._rgb = None
        self._rgb_animator = None
        self._last_input_time: float = 0.0
        self._rgb_activity_state: str = 'active'
        self._activity_tracking: bool = False
        self._idle_after: float = 30.0
        self._sleep_after: float = 300.0
        self._physical = None
        self._grabbed_devices = []
        self._running = False
        self._profile: ProfileManager | None = None
        self._ipc: IPCServer | None = ipc_server

        self._raw_left_x = 0
        self._raw_left_y = 0
        self._raw_right_x = 0
        self._raw_right_y = 0

    def start(self):
        """Open devices and start the event loop."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running = True
        try:
            self.gamepad.create(rumble=self._rumble_enabled)

            if self._rumble_enabled and self.discovered.hidraw_path:
                from .rumble import RumbleHandler, init_vibration_modules
                if self.discovered.control_hidraw_path:
                    init_vibration_modules(self.discovered.control_hidraw_path)
                self._rumble = RumbleHandler(self.discovered.hidraw_path)

            if self.discovered.control_hidraw_path:
                from .hid import ControlReader
                from .config import battery_notifications_enabled, battery_notify_thresholds
                thresholds = battery_notify_thresholds() if battery_notifications_enabled() else []
                self._control = ControlReader(self.discovered.control_hidraw_path,
                                              self.discovered.connection_type,
                                              notify_thresholds=thresholds)
                try:
                    self._control.start()
                    self._control.set_input_callbacks(
                        self._on_hid_button, self._on_hid_axis, self.gamepad.syn)
                except OSError as e:
                    log.warning("Battery reader unavailable: %s", e)
                    self._control = None

            if self.discovered.hidraw_path:
                from .hid import AnalogListener
                self._analog = AnalogListener(self.discovered.hidraw_path,
                                              self._on_hid_axis, self.gamepad.syn)
                try:
                    self._analog.start()
                except OSError as e:
                    log.warning("Analog listener unavailable: %s", e)
                    self._analog = None

            if self.discovered.control_hidraw_path:
                from .hid import RGBController
                try:
                    self._rgb = RGBController(self.discovered.control_hidraw_path,
                                              self.discovered.connection_type)
                    self._start_rgb()
                except OSError as e:
                    log.warning("RGB unavailable: %s", e)
                    self._rgb = None

            # Load profiles from config
            config = load_config()
            self._profile = ProfileManager.from_config(config)
            if self._initial_profile:
                try:
                    self._profile.switch(self._initial_profile)
                except KeyError:
                    log.warning("--profile %r not found in config, using default",
                                self._initial_profile)

            from .config import rgb_activity_tracking, rgb_idle_after, rgb_sleep_after
            self._activity_tracking = rgb_activity_tracking()
            self._idle_after = rgb_idle_after()
            self._sleep_after = rgb_sleep_after()
            self._last_input_time = time.monotonic()

            self._reload_input_config()

            if self._ipc is None:
                try:
                    self._ipc = IPCServer()
                except OSError:
                    log.error("IPC socket unavailable — scuf-ctl will not work", exc_info=True)

            self._open_devices()
            self._suppress_competing_gamepads()
            log.info("Bridge started — SCUF -> Xbox translation active (profile: %s)",
                     self._profile.active_name)
            self._run_with_reconnect()
        finally:
            self._cleanup()

    def _run_with_reconnect(self):
        while self._running:
            try:
                self._event_loop()
                break
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
        log.info("Opening physical device: %s", self.discovered.event_path)
        self._physical = evdev.InputDevice(self.discovered.event_path)
        self._physical.grab()
        self._grabbed_devices.append(self._physical)
        log.info("Exclusively grabbed: %s", self._physical.name)

        for sec_path in self.discovered.secondary_event_paths:
            try:
                sec_dev = evdev.InputDevice(sec_path)
                sec_dev.grab()
                self._grabbed_devices.append(sec_dev)
                log.debug("Grabbed secondary (suppressed): %s (%s)", sec_path, sec_dev.name)
            except (OSError, PermissionError) as e:
                log.warning("Could not grab secondary device %s: %s", sec_path, e)

    def _suppress_competing_gamepads(self):
        for path in find_competing_gamepads():
            try:
                dev = evdev.InputDevice(path)
                dev.grab()
                self._grabbed_devices.append(dev)
                log.warning(
                    "OpenLinkHub virtual gamepad suppressed: %s (%s). "
                    "To avoid HID command conflicts, set \"enableGamepad\": false "
                    "in /opt/OpenLinkHub/config.json and restart OpenLinkHub.",
                    path, dev.name,
                )
            except OSError as e:
                log.warning("Could not suppress competing gamepad %s: %s", path, e)

    def _event_loop(self):
        """Main event loop — interrupt-driven via select, effectively 500 Hz.

        All input (buttons, axes, triggers) arrives via HID raw callbacks (_on_hid_button,
        _on_hid_axis) from ControlReader and AnalogListener threads. The physical evdev fd
        is held grabbed here only to detect disconnect and suppress double-input to other
        processes — evdev events are drained without being processed.
        """
        phys_fd = self._physical.fd
        poll = select.poll()
        poll.register(phys_fd, select.POLLIN)
        timeout = _poll_timeout_ms()

        vgpad_fd = self.gamepad.fd if self._rumble else -1
        if vgpad_fd >= 0:
            poll.register(vgpad_fd, select.POLLIN)

        ipc_fd = self._ipc.fileno() if self._ipc else -1
        if ipc_fd >= 0:
            poll.register(ipc_fd, select.POLLIN)

        secondary_fd_map = {dev.fd: dev for dev in self._grabbed_devices
                            if dev is not self._physical}
        for sec_fd in secondary_fd_map:
            poll.register(sec_fd, select.POLLIN)

        while self._running:
            events = poll.poll(timeout)
            self._check_rgb_activity()
            if not events:
                continue

            for ready_fd, _ in events:
                if ready_fd == phys_fd:
                    try:
                        for _ in self._physical.read():
                            pass  # drain; all input arrives via HID raw callbacks
                    except OSError as e:
                        if self._running:
                            log.error("Device read error: %s", e)
                            raise _DeviceDisconnected() from e
                elif ready_fd in secondary_fd_map:
                    try:
                        for _ in secondary_fd_map[ready_fd].read():
                            pass  # drain secondary devices
                    except OSError as e:
                        if self._running:
                            log.error("Secondary device read error: %s", e)
                            raise _DeviceDisconnected() from e
                elif ready_fd == vgpad_fd:
                    self._handle_ff_events()
                elif ready_fd == ipc_fd:
                    self._ipc.handle_request(
                        self._profile, self._build_status_state(),
                        extras={
                            "set_rgb": self._set_rgb_mode,
                            "on_profile_switch": self._on_profile_switch,
                            "on_layer_switch": self._on_layer_switch,
                        }
                    )

    def _on_hid_button(self, code: int, value: int) -> None:
        self._last_input_time = time.monotonic()
        self._dispatch_button(code, value)

    def _on_hid_axis(self, code: int, value: int) -> None:
        self._last_input_time = time.monotonic()
        if code == ecodes.ABS_X:
            self._raw_left_x = value
            self._emit_filtered_stick("left", self._raw_left_x, self._raw_left_y,
                                      ecodes.ABS_X, ecodes.ABS_Y)
        elif code == ecodes.ABS_Y:
            self._raw_left_y = value
            self._emit_filtered_stick("left", self._raw_left_x, self._raw_left_y,
                                      ecodes.ABS_X, ecodes.ABS_Y)
        elif code == ecodes.ABS_RX:
            self._raw_right_x = value
            self._emit_filtered_stick("right", self._raw_right_x, self._raw_right_y,
                                      ecodes.ABS_RX, ecodes.ABS_RY)
        elif code == ecodes.ABS_RY:
            self._raw_right_y = value
            self._emit_filtered_stick("right", self._raw_right_x, self._raw_right_y,
                                      ecodes.ABS_RX, ecodes.ABS_RY)
        elif code == ecodes.ABS_Z:
            filtered = self.filter.filter_trigger(value, side='left')
            filtered, changed = self.filter.suppress_jitter("lt", filtered)
            if changed:
                self.gamepad.emit_axis(ecodes.ABS_Z, filtered)
        elif code == ecodes.ABS_RZ:
            filtered = self.filter.filter_trigger(value, side='right')
            filtered, changed = self.filter.suppress_jitter("rt", filtered)
            if changed:
                self.gamepad.emit_axis(ecodes.ABS_RZ, filtered)
        else:
            # HAT0X/HAT0Y from HID DPAD bitmask — emit raw (integers, no filtering needed)
            self.gamepad.emit_axis(code, value)

    def _handle_ff_events(self):
        ui = self.gamepad.uinput
        try:
            for event in ui.read():
                if event.type == ecodes.EV_UINPUT:
                    if event.code == ecodes.UI_FF_UPLOAD:
                        upload = ui.begin_upload(event.value)
                        effect = upload.effect
                        if effect.type == ecodes.FF_RUMBLE:
                            rumble = effect.u.ff_rumble_effect
                            self._ff_effects[effect.id] = (
                                rumble.strong_magnitude,
                                rumble.weak_magnitude,
                            )
                            log.info("FF upload id=%d: strong=%d weak=%d",
                                     effect.id, rumble.strong_magnitude, rumble.weak_magnitude)
                        else:
                            log.info("FF upload id=%d: non-rumble type=%d (ignored)",
                                     effect.id, effect.type)
                        upload.retval = 0
                        ui.end_upload(upload)
                    elif event.code == ecodes.UI_FF_ERASE:
                        erase = ui.begin_erase(event.value)
                        self._ff_effects.pop(erase.effect_id, None)
                        erase.retval = 0
                        ui.end_erase(erase)
                elif event.type == ecodes.EV_FF:
                    if event.code == ecodes.FF_GAIN:
                        self._ff_gain = max(0, min(65535, event.value))
                        log.info("FF_GAIN set to %d (%.0f%%)", self._ff_gain,
                                 self._ff_gain / 65535 * 100)
                    else:
                        eff = self._ff_effects.get(event.code)
                        if eff and self._rumble:
                            if event.value > 0:
                                strong = eff[0] * self._ff_gain // 65535
                                weak = eff[1] * self._ff_gain // 65535
                                log.info("Rumble play: raw=%d/%d gain=%d scaled=%d/%d",
                                         eff[0], eff[1], self._ff_gain, strong, weak)
                                self._rumble.set_motors(strong, weak)
                            else:
                                log.info("Rumble stop: effect id=%d", event.code)
                                self._rumble.stop()
        except OSError as e:
            log.debug("FF read error (non-fatal): %s", e)

    def _emit_filtered_stick(self, stick_name: str, raw_x: int, raw_y: int,
                              out_x_code: int, out_y_code: int):
        fx, fy = self.filter.filter_stick(raw_x, raw_y, stick=stick_name)
        fx, x_changed = self.filter.suppress_jitter(f"{stick_name}_x", fx)
        fy, y_changed = self.filter.suppress_jitter(f"{stick_name}_y", fy)
        if x_changed or y_changed:
            self.gamepad.emit_axis(out_x_code, fx)
            self.gamepad.emit_axis(out_y_code, fy)

    def _reload_input_config(self) -> None:
        """Rebuild InputFilter from config (per-profile or global [input] section)."""
        from .config import input_params
        p = input_params(self._profile.active_name if self._profile else None)
        self.filter = InputFilter(
            left_stick_deadzone=p['left_stick_deadzone_sw'],
            right_stick_deadzone=p['right_stick_deadzone_sw'],
            left_stick_anti_dz=p['left_stick_anti_deadzone'],
            right_stick_anti_dz=p['right_stick_anti_deadzone'],
            left_trigger_deadzone=p['left_trigger_deadzone_sw'],
            right_trigger_deadzone=p['right_trigger_deadzone_sw'],
            jitter_threshold=p['jitter_threshold'],
            stick_curve=p['stick_curve'],
            trigger_curve=p['trigger_curve'],
        )
        log.debug("Input filter reloaded: L_sw=%d R_sw=%d L_anti=%d R_anti=%d jitter=%d",
                  p['left_stick_deadzone_sw'], p['right_stick_deadzone_sw'],
                  p['left_stick_anti_deadzone'], p['right_stick_anti_deadzone'],
                  p['jitter_threshold'])

    def _on_profile_switch(self) -> None:
        import threading
        from .hid import _notify
        self._rgb_activity_state = ''
        self._reload_input_config()
        threading.Thread(target=_notify,
                         args=("SCUF Profile", f"Switched to: {self._profile.active_name}"),
                         daemon=True).start()

    def _on_layer_switch(self, layer_name: str) -> None:
        import threading
        from .hid import _notify
        threading.Thread(target=_notify,
                         args=("SCUF Layer", f"Switched to: {layer_name}"),
                         daemon=True).start()
        log.info("Layer switched to: %s", layer_name)

    def _check_rgb_activity(self) -> None:
        if not self._activity_tracking or self._rgb is None:
            return
        elapsed = time.monotonic() - self._last_input_time
        new = ('sleep' if elapsed >= self._sleep_after
               else 'idle' if elapsed >= self._idle_after
               else 'active')
        if new == self._rgb_activity_state:
            return
        self._rgb_activity_state = new
        from .config import rgb_state_params
        p = rgb_state_params(new, self._profile.active_name if self._profile else None)
        self._set_rgb_mode(p.pop('mode'), **p)
        log.info("RGB activity state → %s", new)

    def _start_rgb(self) -> None:
        from .rgb import RGBAnimator
        if self._activity_tracking:
            from .config import rgb_state_params
            params = rgb_state_params('active', self._profile.active_name if self._profile else None)
        else:
            from .config import rgb_mode, rgb_color, rgb_color2, rgb_speed, rgb_brightness
            r, g, b = rgb_color()
            r2, g2, b2 = rgb_color2()
            params = dict(mode=rgb_mode(), r=r, g=g, b=b, r2=r2, g2=g2, b2=b2,
                          speed=rgb_speed(), brightness=rgb_brightness())
        mode = params.pop('mode')
        self._rgb_animator = RGBAnimator(self._rgb, mode, **params)
        self._rgb_animator.start()
        log.info("RGB mode: %s", mode)

    def _stop_rgb(self) -> None:
        if self._rgb_animator:
            self._rgb_animator.stop()
            self._rgb_animator = None
        if self._rgb:
            self._rgb.close()
            self._rgb = None

    def _set_rgb_mode(self, mode: str, **params) -> None:
        """IPC callback: stop current animator, start a new one with given mode/params."""
        if self._rgb_animator:
            self._rgb_animator.stop()
            self._rgb_animator = None
        if self._rgb:
            from .rgb import RGBAnimator
            self._rgb_animator = RGBAnimator(self._rgb, mode, **params)
            self._rgb_animator.start()

    def _build_status_state(self) -> dict:
        from . import __version__
        return {
            "driver_version": __version__,
            "device": self.discovered.event_path,
            "connection": self.discovered.connection_type,
            "rumble": self._rumble_enabled,
            "rgb": self._rgb is not None,
            "battery": self._control.level if self._control else -1,
            "pid": os.getpid(),
            "layer": self._profile.active_layer if self._profile else None,
            "layers": self._profile.active_layers if self._profile else [],
        }

    def _release_physical(self):
        for dev in self._grabbed_devices:
            try:
                dev.ungrab()
                dev.close()
            except OSError:
                pass
        self._grabbed_devices.clear()
        self._physical = None

    def _zero_virtual_outputs(self):
        from .constants import VIRTUAL_BUTTONS
        if self._rumble:
            self._rumble.stop()
        for axis in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY,
                     ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
            self.gamepad.emit_axis(axis, 0)
        for code in VIRTUAL_BUTTONS:
            self.gamepad.emit_button(code, 0)
        self.gamepad.syn()
        self._raw_left_x = self._raw_left_y = 0
        self._raw_right_x = self._raw_right_y = 0

    def _wait_for_reconnect(self, poll_interval: float = 2.0) -> bool:
        while self._running:
            time.sleep(poll_interval)
            discovered = discover_scuf()
            if discovered is None:
                continue
            self.discovered = discovered
            try:
                self._open_devices()
                from .audio_control import apply_audio_config
                try:
                    apply_audio_config()
                except Exception:
                    pass
                if self._rumble_enabled and discovered.hidraw_path:
                    from .rumble import RumbleHandler, init_vibration_modules
                    if self._rumble:
                        self._rumble.close()
                    if discovered.control_hidraw_path:
                        init_vibration_modules(discovered.control_hidraw_path)
                    self._rumble = RumbleHandler(discovered.hidraw_path)
                if self._control:
                    self._control.close()
                    self._control = None
                if discovered.control_hidraw_path:
                    from .hid import ControlReader
                    from .config import battery_notifications_enabled, battery_notify_thresholds
                    thresholds = battery_notify_thresholds() if battery_notifications_enabled() else []
                    self._control = ControlReader(discovered.control_hidraw_path,
                                                  discovered.connection_type,
                                                  notify_thresholds=thresholds)
                    try:
                        self._control.start()
                        self._control.set_input_callbacks(
                            self._on_hid_button, self._on_hid_axis, self.gamepad.syn)
                    except OSError as e:
                        log.warning("Battery reader unavailable after reconnect: %s", e)
                        self._control = None
                if self._analog:
                    self._analog.close()
                    self._analog = None
                if discovered.hidraw_path:
                    from .hid import AnalogListener
                    self._analog = AnalogListener(discovered.hidraw_path,
                                                  self._on_hid_axis, self.gamepad.syn)
                    try:
                        self._analog.start()
                    except OSError as e:
                        log.warning("Analog listener unavailable after reconnect: %s", e)
                        self._analog = None
                self._stop_rgb()
                if discovered.control_hidraw_path:
                    from .hid import RGBController
                    try:
                        self._rgb = RGBController(discovered.control_hidraw_path,
                                                  discovered.connection_type)
                        self._start_rgb()
                    except OSError as e:
                        log.warning("RGB unavailable after reconnect: %s", e)
                self._reload_input_config()
                return True
            except OSError as e:
                log.warning("Device found but failed to open: %s", e)
        return False

    def _signal_handler(self, signum, frame):
        log.info("Received signal %d, shutting down...", signum)
        self._running = False

    def _cleanup(self):
        log.info("Cleaning up...")
        if self._ipc:
            self._ipc.close()
            self._ipc = None
        if self._rumble:
            self._rumble.close()
            self._rumble = None
        if self._control:
            self._control.close()
            self._control = None
        if self._analog:
            self._analog.close()
            self._analog = None
        self._stop_rgb()
        self._release_physical()
        self.gamepad.close()
        log.info("Cleanup complete")


def _sleep_polling_ipc(ipc, duration: float) -> None:
    """Sleep for duration seconds, servicing any IPC requests that arrive."""
    if ipc is None:
        time.sleep(duration)
        return
    poll = select.poll()
    poll.register(ipc.fileno(), select.POLLIN)
    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        for _fd, _ in poll.poll(min(remaining * 1000, 100)):
            ipc.handle_request(None, None)


def _discover_with_ipc_poll(ipc, max_attempts: int = 15, interval: float = 2.0):
    for attempt in range(1, max_attempts + 1):
        result = discover_scuf()
        if result is not None:
            return result
        if attempt < max_attempts:
            log.info("Controller not found, waiting for device enumeration... "
                     "(attempt %d/%d, next retry in %.0fs)", attempt, max_attempts, interval)
            _sleep_polling_ipc(ipc, interval)
    return None


def run(initial_profile: str | None = None):
    """Entry point: discover device and run the bridge."""
    from . import __version__
    log.info("SCUF Envision Pro V2 Linux Driver v%s starting...", __version__)

    ipc = None
    try:
        ipc = IPCServer()
    except OSError:
        log.error("IPC socket unavailable — scuf-ctl will not work", exc_info=True)

    discovered = _discover_with_ipc_poll(ipc)
    if discovered is None:
        log.error("No SCUF Envision Pro V2 controller found after 30s!")
        log.error("Make sure the controller is plugged in via USB or wireless receiver is connected.")
        log.error("Check: lsusb | grep 1b1c")
        if ipc:
            ipc.close()
        sys.exit(1)

    log.info("Found controller: %s", discovered)

    from .audio_control import apply_audio_config
    try:
        apply_audio_config()
    except Exception as e:
        log.warning("Could not apply audio config: %s", e)

    from .config import is_rumble_disabled
    rumble_enabled = not is_rumble_disabled()
    if rumble_enabled and discovered.hidraw_path:
        log.info("Rumble enabled (hidraw: %s)", discovered.hidraw_path)
    elif rumble_enabled:
        log.warning("Rumble enabled in config but no hidraw device found — rumble unavailable")
        rumble_enabled = False
    else:
        log.info("Rumble disabled by config")

    reconnect = (discovered.connection_type == "wireless")
    if reconnect:
        log.info("Wireless mode: reconnection on disconnect is enabled")

    bridge = BridgeService(discovered, reconnect=reconnect, rumble_enabled=rumble_enabled,
                           initial_profile=initial_profile, ipc_server=ipc)
    bridge.start()
