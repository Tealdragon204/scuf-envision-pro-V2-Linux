"""
Input filtering: radial deadzone, trigger deadzone, and jitter suppression.
"""

import math
from .constants import (
    STICK_DEADZONE, TRIGGER_DEADZONE, STICK_JITTER_THRESHOLD,
    STICK_MIN, STICK_MAX, TRIGGER_MIN, TRIGGER_MAX,
)


class InputFilter:
    """Filters stick and trigger values for clean output."""

    def __init__(self, stick_deadzone: int = STICK_DEADZONE,
                 trigger_deadzone: int = TRIGGER_DEADZONE,
                 jitter_threshold: int = STICK_JITTER_THRESHOLD):
        self.stick_deadzone = stick_deadzone
        self.trigger_deadzone = trigger_deadzone
        self.jitter_threshold = jitter_threshold

        # Last output values for jitter suppression
        self._last = {}

    def filter_stick(self, x: int, y: int) -> tuple:
        """
        Apply radial deadzone to a stick pair.

        Uses circular deadzone (sqrt(x^2 + y^2)) rather than per-axis square
        deadzone for smoother diagonal response.

        Returns (filtered_x, filtered_y).
        """
        magnitude = math.sqrt(x * x + y * y)

        if magnitude < self.stick_deadzone:
            return 0, 0

        # Scale the output so it starts from 0 at the deadzone edge
        # and reaches full range at max deflection
        max_magnitude = STICK_MAX  # 32767
        scale = (magnitude - self.stick_deadzone) / (max_magnitude - self.stick_deadzone)
        scale = min(scale, 1.0)

        # Preserve direction, apply scaled magnitude
        if magnitude > 0:
            nx = x / magnitude
            ny = y / magnitude
        else:
            nx, ny = 0.0, 0.0

        out_x = int(nx * scale * max_magnitude)
        out_y = int(ny * scale * max_magnitude)

        # Clamp
        out_x = max(STICK_MIN, min(STICK_MAX, out_x))
        out_y = max(STICK_MIN, min(STICK_MAX, out_y))

        return out_x, out_y

    def filter_trigger(self, value: int) -> int:
        """Apply deadzone to a trigger value."""
        if value < self.trigger_deadzone:
            return 0
        return value

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
