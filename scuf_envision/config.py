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
