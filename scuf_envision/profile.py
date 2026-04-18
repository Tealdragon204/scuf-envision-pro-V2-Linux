"""Named profile management: per-game button remapping on top of hardware defaults."""

import configparser
import logging
from dataclasses import dataclass, field

from evdev import ecodes

from .constants import HID_BUTTON_MAP

log = logging.getLogger(__name__)

_BASE_MAP: dict[int, int] = {code: code for code in HID_BUTTON_MAP.values()}

# Friendly aliases for the config file — users write P1/S1/G1/PROFILE instead of
# BTN_TRIGGER_HAPPY* which are arbitrary kernel slot names with no inherent meaning.
_ALIASES: dict[str, int] = {
    # Face buttons
    "A":       ecodes.BTN_SOUTH,
    "B":       ecodes.BTN_EAST,
    "X":       ecodes.BTN_NORTH,
    "Y":       ecodes.BTN_WEST,
    # Shoulder buttons
    "LB":      ecodes.BTN_TL,
    "RB":      ecodes.BTN_TR,
    # System buttons
    "SELECT":  ecodes.BTN_SELECT,
    "BACK":    ecodes.BTN_SELECT,
    "START":   ecodes.BTN_START,
    "MENU":    ecodes.BTN_START,
    "HOME":    ecodes.BTN_MODE,
    "GUIDE":   ecodes.BTN_MODE,
    # Stick clicks
    "L3":      ecodes.BTN_THUMBL,
    "R3":      ecodes.BTN_THUMBR,
    # Rear paddles
    "P1":      ecodes.BTN_TRIGGER_HAPPY1,
    "P2":      ecodes.BTN_TRIGGER_HAPPY2,
    "P3":      ecodes.BTN_TRIGGER_HAPPY3,
    "P4":      ecodes.BTN_TRIGGER_HAPPY4,
    # SAX grip bumpers
    "S1":      ecodes.BTN_TRIGGER_HAPPY5,
    "S2":      ecodes.BTN_TRIGGER_HAPPY6,
    # G-keys
    "G1":      ecodes.BTN_TRIGGER_HAPPY7,
    "G2":      ecodes.BTN_TRIGGER_HAPPY8,
    "G3":      ecodes.BTN_TRIGGER_HAPPY9,
    "G4":      ecodes.BTN_TRIGGER_HAPPY10,
    "G5":      ecodes.BTN_TRIGGER_HAPPY11,
    # Profile button
    "PROFILE": ecodes.BTN_TRIGGER_HAPPY12,
}


@dataclass
class LayerConfig:
    switch_button: int | None = None
    stack: list[str] = field(default_factory=list)
    layers: dict[str, dict[int, int]] = field(default_factory=dict)
    active_idx: int = 0


def _resolve_code(name: str) -> int | None:
    """Resolve a button name to its evdev integer value.

    Accepts friendly aliases (P1–P4, S1/S2, G1–G5, PROFILE) or any evdev
    code name (BTN_SOUTH, BTN_TL, etc.).
    """
    upper = name.upper().strip()
    if upper in _ALIASES:
        return _ALIASES[upper]
    code = getattr(ecodes, upper, None)
    if code is None or not isinstance(code, int):
        log.warning("Unknown button name %r in profile (skipped)", name)
        return None
    return code


class ProfileManager:
    """Manages named profiles and the active button remap table.

    Profiles are defined as {physical_code: virtual_code} override dicts on top
    of HID_BUTTON_MAP virtual codes. Layers add a second tier of overrides
    within a profile, cycled by a designated switch_button. The effective_button_map
    property reflects the three-way merge: BASE_MAP → profile overrides → layer overrides.
    """

    def __init__(self, profiles: dict[str, dict[int, int]],
                 layer_configs: dict[str, LayerConfig] | None = None):
        self._profiles = profiles
        self._layer_configs: dict[str, LayerConfig] = layer_configs or {}
        self._active = "default"
        self._effective: dict[int, int] = dict(_BASE_MAP)

    @property
    def active_name(self) -> str:
        return self._active

    @property
    def effective_button_map(self) -> dict[int, int]:
        return self._effective

    @property
    def active_layer(self) -> str | None:
        lc = self._layer_configs.get(self._active)
        return lc.stack[lc.active_idx] if lc and lc.stack else None

    @property
    def active_layers(self) -> list[str]:
        lc = self._layer_configs.get(self._active)
        return lc.stack if lc else []

    @property
    def switch_button(self) -> int | None:
        lc = self._layer_configs.get(self._active)
        return lc.switch_button if lc else None

    def _rebuild_effective(self) -> None:
        overrides = self._profiles.get(self._active, {})
        lc = self._layer_configs.get(self._active)
        layer_ovr = lc.layers.get(lc.stack[lc.active_idx], {}) if lc and lc.stack else {}
        self._effective = {**_BASE_MAP, **overrides, **layer_ovr}

    def switch(self, name: str) -> None:
        """Switch to a named profile. Raises KeyError if not found."""
        if name != "default" and name not in self._profiles:
            raise KeyError(name)
        old = self._active
        self._active = name
        lc = self._layer_configs.get(name)
        if lc:
            lc.active_idx = 0
        self._rebuild_effective()
        log.info("Profile switched: %s -> %s (%d override(s))", old, name,
                 len(self._profiles.get(name, {})))

    def cycle_layer(self) -> str | None:
        """Advance to the next layer. Returns new layer name, or None if no layers."""
        lc = self._layer_configs.get(self._active)
        if not lc or not lc.stack:
            return None
        lc.active_idx = (lc.active_idx + 1) % len(lc.stack)
        self._rebuild_effective()
        return lc.stack[lc.active_idx]

    def switch_layer(self, name: str) -> None:
        """Switch to a named layer in the active profile. Raises KeyError if not found."""
        lc = self._layer_configs.get(self._active)
        if lc is None or name not in lc.layers:
            raise KeyError(name)
        lc.active_idx = lc.stack.index(name)
        self._rebuild_effective()

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
            if "." in name:
                continue  # skip .input, .rgb.*, .layers, .layer.* subsections
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

        layer_configs: dict[str, LayerConfig] = {}
        for name in profiles:
            meta = f"profile.{name}.layers"
            if not config.has_section(meta):
                continue
            sw_raw = config.get(meta, "switch_button", fallback=None)
            sw_btn = _resolve_code(sw_raw) if sw_raw else None
            stack = [s.strip() for s in config.get(meta, "stack", fallback="").split(",")
                     if s.strip()]
            layers: dict[str, dict[int, int]] = {}
            for ln in stack:
                sec = f"profile.{name}.layer.{ln}"
                ovr: dict[int, int] = {}
                if config.has_section(sec):
                    for rn, tn in config[sec].items():
                        r, t = _resolve_code(rn), _resolve_code(tn)
                        if r is not None and t is not None:
                            ovr[r] = t
                layers[ln] = ovr
            if stack:
                layer_configs[name] = LayerConfig(
                    switch_button=sw_btn, stack=stack, layers=layers)
                log.debug("Loaded layers for profile %r: %s", name, stack)

        return cls(profiles, layer_configs)
