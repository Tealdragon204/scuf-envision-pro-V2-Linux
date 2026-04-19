"""Unit tests for ProfileManager macro parsing and dispatch (Phase 17)."""

import configparser
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evdev import ecodes
from scuf_envision.profile import ProfileManager, Macro, MacroStep, _parse_macro


def _mgr(ini: str) -> ProfileManager:
    cp = configparser.ConfigParser()
    cp.read_string(ini)
    return ProfileManager.from_config(cp)


class TestParseMacro(unittest.TestCase):

    def test_basic_sequence(self):
        m = _parse_macro("A:50,B:100")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.steps), 2)
        self.assertEqual(m.steps[0].code, ecodes.BTN_SOUTH)
        self.assertAlmostEqual(m.steps[0].hold_ms, 50.0)
        self.assertEqual(m.steps[1].code, ecodes.BTN_EAST)
        self.assertAlmostEqual(m.steps[1].hold_ms, 100.0)

    def test_zero_hold_ms(self):
        m = _parse_macro("X:0")
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.steps[0].hold_ms, 0.0)

    def test_bare_button_name(self):
        m = _parse_macro("A")
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.steps[0].hold_ms, 0.0)
        self.assertEqual(m.steps[0].code, ecodes.BTN_SOUTH)

    def test_invalid_button_skipped(self):
        m = _parse_macro("NOTABUTTON:50,A:30")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.steps), 1)
        self.assertEqual(m.steps[0].code, ecodes.BTN_SOUTH)

    def test_all_invalid_returns_none(self):
        self.assertIsNone(_parse_macro("NOTABUTTON:50"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_macro(""))

    def test_lb_alias(self):
        m = _parse_macro("LB:30")
        self.assertEqual(m.steps[0].code, ecodes.BTN_TL)

    def test_paddle_alias(self):
        m = _parse_macro("P1:50")
        self.assertEqual(m.steps[0].code, ecodes.BTN_TRIGGER_HAPPY1)

    def test_fractional_hold_ms(self):
        m = _parse_macro("A:16.7")
        self.assertAlmostEqual(m.steps[0].hold_ms, 16.7)

    def test_whitespace_tolerance(self):
        m = _parse_macro(" A : 50 , B : 100 ")
        self.assertIsNotNone(m)
        self.assertEqual(len(m.steps), 2)


class TestMacroFromConfig(unittest.TestCase):

    _INI = """
[profile.GAME]
P2 = B

[profile.GAME.macros]
P1 = A:50,B:100,X:0
S1 = LB:30,RB:30
"""

    def test_macros_loaded(self):
        mgr = _mgr(self._INI)
        mgr.switch("GAME")
        mm = mgr.macro_map
        self.assertIn(ecodes.BTN_TRIGGER_HAPPY1, mm)   # P1
        self.assertIn(ecodes.BTN_TRIGGER_HAPPY5, mm)   # S1

    def test_macro_steps_correct(self):
        mgr = _mgr(self._INI)
        mgr.switch("GAME")
        m = mgr.macro_map[ecodes.BTN_TRIGGER_HAPPY1]
        self.assertEqual(len(m.steps), 3)
        self.assertEqual(m.steps[0].code, ecodes.BTN_SOUTH)
        self.assertAlmostEqual(m.steps[0].hold_ms, 50.0)
        self.assertEqual(m.steps[1].code, ecodes.BTN_EAST)
        self.assertAlmostEqual(m.steps[2].hold_ms, 0.0)

    def test_macro_map_empty_on_default_profile(self):
        mgr = _mgr(self._INI)
        self.assertEqual(mgr.macro_map, {})

    def test_macros_not_in_profiles_list(self):
        mgr = _mgr(self._INI)
        profiles = mgr.list_profiles()
        self.assertIn("GAME", profiles)
        self.assertNotIn("GAME.macros", profiles)

    def test_macros_isolated_per_profile(self):
        ini = """
[profile.A]
[profile.A.macros]
P1 = X:50
[profile.B]
"""
        mgr = _mgr(ini)
        mgr.switch("A")
        self.assertIn(ecodes.BTN_TRIGGER_HAPPY1, mgr.macro_map)
        mgr.switch("B")
        self.assertNotIn(ecodes.BTN_TRIGGER_HAPPY1, mgr.macro_map)

    def test_normal_remap_coexists_with_macros(self):
        # P2 has a normal remap; P1 has a macro — both should be accessible
        mgr = _mgr(self._INI)
        mgr.switch("GAME")
        # P2 maps to B in effective remap
        self.assertEqual(mgr.effective_button_map.get(ecodes.BTN_TRIGGER_HAPPY2),
                         ecodes.BTN_EAST)
        # P1 has a macro (3 steps)
        self.assertIn(ecodes.BTN_TRIGGER_HAPPY1, mgr.macro_map)
        self.assertEqual(len(mgr.macro_map[ecodes.BTN_TRIGGER_HAPPY1].steps), 3)


if __name__ == "__main__":
    unittest.main()
