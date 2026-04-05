"""Named profile management: per-game button remapping on top of hardware defaults."""

import configparser
import logging

from evdev import ecodes

from .constants import BUTTON_MAP, PADDLE_MAP

log = logging.getLogger(__name__)

_BASE_MAP = {**BUTTON_MAP, **PADDLE_MAP}


def _resolve_code(name: str) -> int | None:
    """Resolve an evdev code name (e.g. 'BTN_SOUTH') to its integer value."""
    code = getattr(ecodes, name.upper().strip(), None)
    if code is None or not isinstance(code, int):
        log.warning("Unknown evdev code %r in profile (skipped)", name)
        return None
    return code


class ProfileManager:
    """Manages named profiles and the active button remap table.

    Profiles are defined as {physical_code: virtual_code} override dicts on top
    of the combined BUTTON_MAP + PADDLE_MAP. The effective_button_map property
    is cached and only recomputed on switch().
    """

    def __init__(self, profiles: dict[str, dict[int, int]]):
        # profiles: name → {physical_code_int: virtual_code_int overrides}
        self._profiles = profiles
        self._active = "default"
        self._effective: dict[int, int] = dict(_BASE_MAP)

    @property
    def active_name(self) -> str:
        return self._active

    @property
    def effective_button_map(self) -> dict[int, int]:
        return self._effective

    def switch(self, name: str) -> None:
        """Switch to a named profile. Raises KeyError if not found."""
        if name != "default" and name not in self._profiles:
            raise KeyError(name)
        old = self._active
        self._active = name
        overrides = self._profiles.get(name, {})
        self._effective = {**_BASE_MAP, **overrides}
        log.info("Profile switched: %s -> %s (%d override(s))", old, name, len(overrides))

    def list_profiles(self) -> list[str]:
        return ["default"] + sorted(k for k in self._profiles if k != "default")

    @classmethod
    def from_config(cls, config: configparser.ConfigParser) -> "ProfileManager":
        """Build a ProfileManager from a loaded ConfigParser instance."""
        profiles: dict[str, dict[int, int]] = {}
        prefix = "profile."
        for section in config.sections():
            if not section.startswith(prefix):
                continue
            name = section[len(prefix):]
            overrides: dict[int, int] = {}
            for raw_name, target_name in config[section].items():
                raw = _resolve_code(raw_name)
                target = _resolve_code(target_name)
                if raw is not None and target is not None:
                    overrides[raw] = target
            profiles[name] = overrides
            log.debug("Loaded profile %r: %d override(s)", name, len(overrides))

        n = len(profiles)
        if n:
            log.info("Loaded %d profile(s): %s", n, ", ".join(sorted(profiles)))
        return cls(profiles)
