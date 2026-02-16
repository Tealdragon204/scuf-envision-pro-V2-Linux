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
