"""
Configuration file management for SCUF Envision Pro V2 driver.

Config path: /etc/scuf-envision/config.ini
"""

import configparser
import logging
import os

log = logging.getLogger(__name__)

CONFIG_DIR = "/etc/scuf-envision"
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.ini")

DEFAULTS = {
    "audio": {
        "disabled": "false",
    },
    "rumble": {
        "disabled": "false",
    },
    "battery": {
        "notifications": "true",
        "notify_thresholds": "20,10,5,1",
    },
    "driver": {
        "poll_timeout_ms": "2",
    },
    "rgb": {
        "mode": "static",
        "color": "255,255,255",
        "color2": "0,0,255",
        "speed": "1.0",
        "brightness": "100",
        "activity_tracking": "false",
        "idle_after": "30",
        "sleep_after": "300",
    },
    "rgb.active": {
        "mode": "static",
        "color": "255,255,255",
        "color2": "0,0,255",
        "speed": "1.0",
        "brightness": "100",
    },
    "rgb.idle": {
        "mode": "static",
        "color": "255,255,255",
        "color2": "0,0,255",
        "speed": "1.0",
        "brightness": "20",
    },
    "rgb.sleep": {
        "mode": "off",
        "color": "0,0,0",
        "color2": "0,0,0",
        "speed": "1.0",
        "brightness": "0",
    },
    "input": {
        "left_stick_deadzone_hw":    "2",
        "right_stick_deadzone_hw":   "2",
        "left_stick_deadzone_sw":    "200",
        "right_stick_deadzone_sw":   "200",
        "left_stick_anti_deadzone":  "0",
        "right_stick_anti_deadzone": "0",
        "left_trigger_deadzone_hw":  "1",
        "right_trigger_deadzone_hw": "1",
        "left_trigger_deadzone_sw":  "5",
        "right_trigger_deadzone_sw": "5",
        "jitter_threshold":          "32",
    },
}


def load_config():
    """Load config from disk, falling back to defaults if file is missing or malformed."""
    config = configparser.ConfigParser()
    for section, values in DEFAULTS.items():
        config[section] = dict(values)

    if os.path.isfile(CONFIG_PATH):
        try:
            config.read(CONFIG_PATH)
            log.debug("Loaded config from %s", CONFIG_PATH)
        except configparser.Error as e:
            log.warning("Malformed config at %s, using defaults: %s", CONFIG_PATH, e)
    else:
        log.debug("No config file at %s, using defaults", CONFIG_PATH)

    return config


def save_config(config):
    """Write config to disk, creating directory if needed."""
    os.makedirs(CONFIG_DIR, mode=0o755, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        config.write(f)
    log.info("Saved config to %s", CONFIG_PATH)


def is_audio_disabled():
    """Return True if audio.disabled is set to true in config."""
    config = load_config()
    return config.getboolean("audio", "disabled", fallback=False)


def set_audio_disabled(disabled):
    """Set the audio.disabled flag and persist to disk."""
    config = load_config()
    if "audio" not in config:
        config["audio"] = {}
    config["audio"]["disabled"] = str(disabled).lower()
    save_config(config)


def is_rumble_disabled():
    """Return True if rumble.disabled is set to true in config."""
    config = load_config()
    return config.getboolean("rumble", "disabled", fallback=False)


def battery_notifications_enabled() -> bool:
    """Return True if low-battery desktop notifications are enabled."""
    config = load_config()
    return config.getboolean("battery", "notifications", fallback=True)


def poll_timeout_ms() -> int:
    """Return poll timeout in ms (default 2 = 500 Hz, matches hardware).

    Does not affect in-game input latency — the event loop is interrupt-driven
    and wakes immediately on hardware events regardless of this value.
    Increase only to reduce idle CPU on battery-powered systems.
    """
    return load_config().getint("driver", "poll_timeout_ms", fallback=2)


def load_profiles() -> dict[str, dict[str, str]]:
    """Return {profile_name: {physical_code_str: virtual_code_str}} from config.

    Scans all [profile.*] sections. Returns raw string names; evdev resolution
    is left to ProfileManager.from_config() to keep this module evdev-free.
    """
    config = load_config()
    prefix = "profile."
    return {
        section[len(prefix):]: dict(config[section])
        for section in config.sections()
        if section.startswith(prefix)
    }


def rgb_mode() -> str:
    """Return animation mode name from config, validated against RGB_MODES."""
    from .rgb import RGB_MODES
    mode = load_config().get("rgb", "mode", fallback="static")
    return mode if mode in RGB_MODES else "static"


def rgb_color2() -> tuple[int, int, int]:
    """Return secondary (r, g, b) color from config, defaulting to blue."""
    raw = load_config().get("rgb", "color2", fallback="0,0,255")
    try:
        parts = [max(0, min(255, int(x.strip()))) for x in raw.split(",")]
        if len(parts) == 3:
            return tuple(parts)
    except ValueError:
        pass
    return (0, 0, 255)


def rgb_speed() -> float:
    """Return animation speed multiplier (0.1–20.0) from config."""
    try:
        v = float(load_config().get("rgb", "speed", fallback="1.0"))
        return max(0.1, min(20.0, v))
    except ValueError:
        return 1.0


def rgb_color() -> tuple[int, int, int]:
    """Return (r, g, b) from config, defaulting to white."""
    raw = load_config().get("rgb", "color", fallback="255,255,255")
    try:
        parts = [max(0, min(255, int(x.strip()))) for x in raw.split(",")]
        if len(parts) == 3:
            return tuple(parts)
    except ValueError:
        pass
    return (255, 255, 255)


def rgb_brightness() -> int:
    """Return brightness 0-100 from config."""
    return max(0, min(100, load_config().getint("rgb", "brightness", fallback=100)))


def rgb_activity_tracking() -> bool:
    """Return True if activity-based RGB state machine is enabled."""
    return load_config().getboolean("rgb", "activity_tracking", fallback=False)


def rgb_idle_after() -> float:
    """Return seconds of no input before transitioning to idle state."""
    try:
        return max(1.0, float(load_config().get("rgb", "idle_after", fallback="30")))
    except ValueError:
        return 30.0


def rgb_sleep_after() -> float:
    """Return seconds of no input before transitioning to sleep state."""
    try:
        return max(1.0, float(load_config().get("rgb", "sleep_after", fallback="300")))
    except ValueError:
        return 300.0


def _parse_color(raw: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    try:
        parts = [max(0, min(255, int(x.strip()))) for x in raw.split(",")]
        if len(parts) == 3:
            return tuple(parts)
    except ValueError:
        pass
    return fallback


def rgb_state_params(state: str, profile_name: str | None = None) -> dict:
    """Return full RGB param dict for an activity state.

    Looks up [profile.NAME.rgb.STATE] first if profile_name is given and the
    section exists; falls back to [rgb.STATE]. Returns keys:
    mode, r, g, b, r2, g2, b2, speed, brightness.
    """
    from .rgb import RGB_MODES
    config = load_config()
    section = f"profile.{profile_name}.rgb.{state}" if profile_name else None
    if not (section and config.has_section(section)):
        section = f"rgb.{state}"

    def get(key, fallback):
        return config.get(section, key, fallback=fallback) if config.has_section(section) else fallback

    mode = get("mode", "static" if state != "sleep" else "off")
    if mode not in RGB_MODES:
        mode = "static"
    r, g, b = _parse_color(get("color", "255,255,255"), (255, 255, 255))
    r2, g2, b2 = _parse_color(get("color2", "0,0,255"), (0, 0, 255))
    try:
        speed = max(0.1, min(20.0, float(get("speed", "1.0"))))
    except ValueError:
        speed = 1.0
    try:
        brightness = max(0, min(100, int(get("brightness", "100"))))
    except ValueError:
        brightness = 100
    return dict(mode=mode, r=r, g=g, b=b, r2=r2, g2=g2, b2=b2,
                speed=speed, brightness=brightness)


def input_params(profile_name: str | None = None) -> dict:
    """Return input filter configuration, with optional per-profile override.

    Looks up [profile.NAME.input] first if profile_name given; falls back to [input].
    """
    config = load_config()
    section = f"profile.{profile_name}.input" if profile_name else None
    if not (section and config.has_section(section)):
        section = "input"

    def gi(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(config.get(section, key, fallback=str(default)))))
        except ValueError:
            return default

    return {
        "left_stick_deadzone_hw":    gi("left_stick_deadzone_hw",    2,   0, 15),
        "right_stick_deadzone_hw":   gi("right_stick_deadzone_hw",   2,   0, 15),
        "left_stick_deadzone_sw":    gi("left_stick_deadzone_sw",    200, 0, 32767),
        "right_stick_deadzone_sw":   gi("right_stick_deadzone_sw",   200, 0, 32767),
        "left_stick_anti_deadzone":  gi("left_stick_anti_deadzone",  0,   0, 32767),
        "right_stick_anti_deadzone": gi("right_stick_anti_deadzone", 0,   0, 32767),
        "left_trigger_deadzone_hw":  gi("left_trigger_deadzone_hw",  1,   0, 15),
        "right_trigger_deadzone_hw": gi("right_trigger_deadzone_hw", 1,   0, 15),
        "left_trigger_deadzone_sw":  gi("left_trigger_deadzone_sw",  5,   0, 1023),
        "right_trigger_deadzone_sw": gi("right_trigger_deadzone_sw", 5,   0, 1023),
        "jitter_threshold":          gi("jitter_threshold",          32,  0, 1000),
    }


def battery_notify_thresholds() -> list[int]:
    """Return sorted descending list of battery % thresholds that trigger notifications."""
    config = load_config()
    raw = config.get("battery", "notify_thresholds", fallback="20,10,5,1")
    try:
        thresholds = [int(x.strip()) for x in raw.split(",") if x.strip()]
        return sorted(set(t for t in thresholds if 0 < t <= 100), reverse=True)
    except ValueError:
        log.warning("Invalid battery.notify_thresholds %r, using defaults", raw)
        return [20, 10, 5, 1]
