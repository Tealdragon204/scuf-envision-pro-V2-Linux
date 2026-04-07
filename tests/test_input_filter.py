"""Unit tests for InputFilter — deadzone math, anti-deadzone, jitter suppression."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scuf_envision.input_filter import InputFilter
from scuf_envision.constants import STICK_MAX, STICK_MIN


def make_filter(**kw):
    defaults = dict(
        left_stick_deadzone=200,
        right_stick_deadzone=200,
        left_stick_anti_dz=0,
        right_stick_anti_dz=0,
        left_trigger_deadzone=5,
        right_trigger_deadzone=5,
        jitter_threshold=32,
    )
    defaults.update(kw)
    return InputFilter(**defaults)


class TestDeadzone(unittest.TestCase):

    def test_zero_input(self):
        f = make_filter()
        self.assertEqual(f.filter_stick(0, 0), (0, 0))

    def test_below_deadzone_suppressed(self):
        f = make_filter(left_stick_deadzone=200)
        self.assertEqual(f.filter_stick(150, 0), (0, 0))
        self.assertEqual(f.filter_stick(0, 150), (0, 0))
        self.assertEqual(f.filter_stick(141, 141), (0, 0))  # mag ≈ 199.4

    def test_above_deadzone_passes(self):
        f = make_filter(left_stick_deadzone=200)
        x, y = f.filter_stick(201, 0)
        self.assertGreater(x, 0)
        self.assertEqual(y, 0)

    def test_max_deflection_reaches_stick_max(self):
        f = make_filter()
        x, y = f.filter_stick(STICK_MAX, 0)
        self.assertEqual(x, STICK_MAX)
        self.assertEqual(y, 0)

    def test_negative_max_deflection(self):
        f = make_filter()
        x, y = f.filter_stick(0, STICK_MIN)
        self.assertEqual(x, 0)
        self.assertLessEqual(y, -STICK_MAX + 1)  # clamped to STICK_MIN

    def test_radial_diagonal_consistency(self):
        # Diagonal at max: each component should be ≈ STICK_MAX / sqrt(2) ≈ 23170
        f = make_filter()
        x, y = f.filter_stick(STICK_MAX, STICK_MAX)
        self.assertGreaterEqual(x, 23000)
        self.assertGreaterEqual(y, 23000)
        self.assertLessEqual(x, STICK_MAX)
        self.assertLessEqual(y, STICK_MAX)

    def test_per_stick_independent_deadzones(self):
        f = make_filter(left_stick_deadzone=200, right_stick_deadzone=5000)
        # 300 clears left DZ but not right
        lx, _ = f.filter_stick(300, 0, stick='left')
        rx, _ = f.filter_stick(300, 0, stick='right')
        self.assertGreater(lx, 0)
        self.assertEqual(rx, 0)

    def test_no_range_compression(self):
        """Max input must still reach STICK_MAX regardless of deadzone size."""
        f = make_filter(left_stick_deadzone=5000)
        x, y = f.filter_stick(STICK_MAX, 0)
        self.assertEqual(x, STICK_MAX)


class TestAntiDeadzone(unittest.TestCase):

    def test_zero_stays_zero(self):
        f = make_filter(left_stick_anti_dz=7000)
        self.assertEqual(f.filter_stick(0, 0, stick='left'), (0, 0))

    def test_nonzero_reaches_floor(self):
        f = make_filter(left_stick_deadzone=200, left_stick_anti_dz=7000)
        x, _ = f.filter_stick(500, 0, stick='left')
        self.assertGreaterEqual(abs(x), 7000)

    def test_max_still_reaches_stick_max(self):
        f = make_filter(left_stick_anti_dz=7000)
        x, _ = f.filter_stick(STICK_MAX, 0, stick='left')
        self.assertEqual(x, STICK_MAX)

    def test_anti_dz_off_by_default(self):
        f = make_filter(left_stick_anti_dz=0, left_stick_deadzone=200)
        x, _ = f.filter_stick(500, 0, stick='left')
        # Should be a small positive value well below 7000
        self.assertGreater(x, 0)
        self.assertLess(x, 1000)

    def test_per_stick_anti_dz_independence(self):
        f = make_filter(left_stick_deadzone=200, right_stick_deadzone=200,
                        left_stick_anti_dz=8000, right_stick_anti_dz=0)
        lx, _ = f.filter_stick(500, 0, stick='left')
        rx, _ = f.filter_stick(500, 0, stick='right')
        self.assertGreaterEqual(lx, 8000)
        self.assertLess(rx, 1000)

    def test_negative_direction_preserved(self):
        f = make_filter(left_stick_anti_dz=5000)
        x, _ = f.filter_stick(-STICK_MAX, 0, stick='left')
        self.assertLessEqual(x, -5000)


class TestTrigger(unittest.TestCase):

    def test_below_deadzone_blocked(self):
        f = make_filter(left_trigger_deadzone=5, right_trigger_deadzone=10)
        self.assertEqual(f.filter_trigger(3, side='left'), 0)
        self.assertEqual(f.filter_trigger(9, side='right'), 0)

    def test_at_threshold_passes(self):
        f = make_filter(left_trigger_deadzone=5)
        self.assertEqual(f.filter_trigger(5, side='left'), 5)

    def test_above_threshold_passes(self):
        f = make_filter(left_trigger_deadzone=5, right_trigger_deadzone=10)
        self.assertEqual(f.filter_trigger(100, side='left'), 100)
        self.assertEqual(f.filter_trigger(100, side='right'), 100)

    def test_per_side_independence(self):
        f = make_filter(left_trigger_deadzone=5, right_trigger_deadzone=50)
        self.assertEqual(f.filter_trigger(20, side='left'), 20)   # passes left
        self.assertEqual(f.filter_trigger(20, side='right'), 0)   # blocked by right


class TestJitter(unittest.TestCase):

    def test_first_call_always_changed(self):
        f = make_filter(jitter_threshold=32)
        val, changed = f.suppress_jitter('x', 500)
        self.assertEqual(val, 500)
        self.assertTrue(changed)

    def test_small_change_suppressed(self):
        f = make_filter(jitter_threshold=32)
        f.suppress_jitter('x', 500)
        val, changed = f.suppress_jitter('x', 515)  # delta=15 < 32
        self.assertEqual(val, 500)
        self.assertFalse(changed)

    def test_large_change_passes(self):
        f = make_filter(jitter_threshold=32)
        f.suppress_jitter('x', 500)
        val, changed = f.suppress_jitter('x', 535)  # delta=35 ≥ 32
        self.assertEqual(val, 535)
        self.assertTrue(changed)

    def test_independent_keys(self):
        f = make_filter(jitter_threshold=32)
        f.suppress_jitter('x', 500)
        f.suppress_jitter('y', 200)
        # Small change on x suppressed, but y is independent
        _, x_changed = f.suppress_jitter('x', 510)
        _, y_changed = f.suppress_jitter('y', 240)
        self.assertFalse(x_changed)
        self.assertTrue(y_changed)

    def test_zero_threshold_always_passes(self):
        f = make_filter(jitter_threshold=0)
        f.suppress_jitter('x', 500)
        val, changed = f.suppress_jitter('x', 501)
        self.assertEqual(val, 501)
        self.assertTrue(changed)


if __name__ == '__main__':
    unittest.main()
