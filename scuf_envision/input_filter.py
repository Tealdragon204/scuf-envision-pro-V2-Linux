"""
Input filtering: radial deadzone, trigger deadzone, anti-deadzone, and jitter suppression.
"""

import math
from .constants import (
    STICK_DEADZONE, TRIGGER_DEADZONE, STICK_JITTER_THRESHOLD,
    STICK_MIN, STICK_MAX, TRIGGER_MIN, TRIGGER_MAX,
)


class InputFilter:
    """Filters stick and trigger values for clean output."""

    def __init__(self,
                 left_stick_deadzone: int = STICK_DEADZONE,
                 right_stick_deadzone: int = STICK_DEADZONE,
                 left_stick_anti_dz: int = 0,
                 right_stick_anti_dz: int = 0,
                 left_trigger_deadzone: int = TRIGGER_DEADZONE,
                 right_trigger_deadzone: int = TRIGGER_DEADZONE,
                 jitter_threshold: int = STICK_JITTER_THRESHOLD):
        self.left_stick_deadzone = left_stick_deadzone
        self.right_stick_deadzone = right_stick_deadzone
        self.left_stick_anti_dz = left_stick_anti_dz
        self.right_stick_anti_dz = right_stick_anti_dz
        self.left_trigger_deadzone = left_trigger_deadzone
        self.right_trigger_deadzone = right_trigger_deadzone
        self.jitter_threshold = jitter_threshold

        # Last output values for jitter suppression
        self._last = {}

    def filter_stick(self, x: int, y: int, stick: str = 'left') -> tuple:
        """
        Apply radial deadzone and anti-deadzone to a stick pair.

        Uses circular deadzone (sqrt(x^2 + y^2)) rather than per-axis square
        deadzone for smoother diagonal response. Anti-deadzone lifts the output
        floor to overcome large game-side deadzones in older titles.

        Returns (filtered_x, filtered_y).
        """
        deadzone = self.left_stick_deadzone if stick == 'left' else self.right_stick_deadzone
        anti_dz = self.left_stick_anti_dz if stick == 'left' else self.right_stick_anti_dz

        magnitude = math.sqrt(x * x + y * y)

        if magnitude < deadzone:
            return 0, 0

        # Scale so deadzone edge → 0, max deflection → STICK_MAX
        scale = min((magnitude - deadzone) / (STICK_MAX - deadzone), 1.0)

        if magnitude > 0:
            nx, ny = x / magnitude, y / magnitude
        else:
            nx, ny = 0.0, 0.0

        out_x = int(nx * scale * STICK_MAX)
        out_y = int(ny * scale * STICK_MAX)

        # Anti-deadzone: lift radial magnitude so no direction-dependent amplification.
        # Applied to magnitude then re-projected, so a 1° off-center push stays 1° off-center.
        if anti_dz:
            out_mag = math.sqrt(out_x * out_x + out_y * out_y)
            if out_mag > 0:
                new_mag = self._apply_anti_deadzone(int(out_mag), anti_dz)
                ratio = new_mag / out_mag
                out_x = int(out_x * ratio)
                out_y = int(out_y * ratio)

        out_x = max(STICK_MIN, min(STICK_MAX, out_x))
        out_y = max(STICK_MIN, min(STICK_MAX, out_y))

        return out_x, out_y

    def _apply_anti_deadzone(self, value: int, anti_dz: int) -> int:
        """Lift the output floor to anti_dz for any non-zero value."""
        if value == 0 or anti_dz == 0:
            return value
        sign = 1 if value > 0 else -1
        mag = abs(value)
        scaled = anti_dz + int((mag - 1) * (STICK_MAX - anti_dz) / (STICK_MAX - 1))
        return sign * min(scaled, STICK_MAX)

    def filter_trigger(self, value: int, side: str = 'left') -> int:
        """Apply deadzone to a trigger value."""
        deadzone = self.left_trigger_deadzone if side == 'left' else self.right_trigger_deadzone
        return 0 if value < deadzone else value

    def suppress_jitter(self, key: str, new_value: int) -> tuple:
        """
        Suppress jitter on a value. Returns (value, changed).

        If the change is smaller than the threshold, returns the old value.
        """
        old = self._last.get(key, None)
        if old is not None and abs(new_value - old) < self.jitter_threshold:
            return old, False
        self._last[key] = new_value
        return new_value, True
