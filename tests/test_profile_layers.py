"""Unit tests for ProfileManager layer stack (Phase 16)."""

import configparser
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evdev import ecodes
from scuf_envision.profile import ProfileManager, LayerConfig
from scuf_envision.constants import BUTTON_MAP, PADDLE_MAP

_BASE = {**BUTTON_MAP, **PADDLE_MAP}
P1 = ecodes.BTN_TRIGGER_HAPPY1
P2 = ecodes.BTN_TRIGGER_HAPPY2
P3 = ecodes.BTN_TRIGGER_HAPPY3
A  = ecodes.BTN_SOUTH
B  = ecodes.BTN_EAST
X  = ecodes.BTN_NORTH
Y  = ecodes.BTN_WEST


def _mgr_from_ini(text: str) -> ProfileManager:
    cp = configparser.ConfigParser()
    cp.read_string(text)
    return ProfileManager.from_config(cp)


class TestNoLayers(unittest.TestCase):
    """Profiles without layers behave exactly as before."""

    def test_default_profile_no_layers(self):
        mgr = _mgr_from_ini("")
        self.assertIsNone(mgr.active_layer)
        self.assertEqual(mgr.active_layers, [])
        self.assertIsNone(mgr.switch_button)
        self.assertEqual(mgr.effective_button_map, _BASE)

    def test_profile_override_no_layers(self):
        mgr = _mgr_from_ini(f"""
[profile.GAME]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
""")
        mgr.switch("GAME")
        self.assertIsNone(mgr.active_layer)
        self.assertEqual(mgr.effective_button_map[P1], A)

    def test_subsections_not_treated_as_profiles(self):
        mgr = _mgr_from_ini(f"""
[profile.GAME]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
[profile.GAME.input]
left_stick_anti_deadzone = 7000
[profile.GAME.rgb.active]
mode = off
""")
        # only GAME should be a profile; GAME.input and GAME.rgb.active must not appear
        self.assertIn("GAME", mgr.list_profiles())
        self.assertNotIn("GAME.input", mgr.list_profiles())
        self.assertNotIn("GAME.rgb.active", mgr.list_profiles())


class TestLayerParsing(unittest.TestCase):

    def _two_layer_mgr(self) -> ProfileManager:
        return _mgr_from_ini(f"""
[profile.GAME]
[profile.GAME.layers]
switch_button = BTN_TRIGGER_HAPPY3
stack = base,combat
[profile.GAME.layer.base]
[profile.GAME.layer.combat]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
BTN_TRIGGER_HAPPY2 = BTN_EAST
""")

    def test_layers_parsed(self):
        mgr = self._two_layer_mgr()
        mgr.switch("GAME")
        self.assertEqual(mgr.active_layers, ["base", "combat"])
        self.assertEqual(mgr.active_layer, "base")
        self.assertEqual(mgr.switch_button, P3)

    def test_base_layer_uses_profile_overrides(self):
        mgr = _mgr_from_ini(f"""
[profile.GAME]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
[profile.GAME.layers]
switch_button = BTN_TRIGGER_HAPPY3
stack = base,alt
[profile.GAME.layer.base]
[profile.GAME.layer.alt]
BTN_TRIGGER_HAPPY1 = BTN_NORTH
""")
        mgr.switch("GAME")
        # base layer: profile override (P1→A) is active, no extra layer overrides
        self.assertEqual(mgr.effective_button_map[P1], A)

    def test_layer_overrides_stack_on_top(self):
        mgr = self._two_layer_mgr()
        mgr.switch("GAME")
        mgr.cycle_layer()  # → combat
        self.assertEqual(mgr.active_layer, "combat")
        self.assertEqual(mgr.effective_button_map[P1], A)
        self.assertEqual(mgr.effective_button_map[P2], B)


class TestCycleLayer(unittest.TestCase):

    def _mgr(self) -> ProfileManager:
        return _mgr_from_ini(f"""
[profile.GAME]
[profile.GAME.layers]
switch_button = BTN_TRIGGER_HAPPY3
stack = base,combat,stealth
[profile.GAME.layer.base]
[profile.GAME.layer.combat]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
[profile.GAME.layer.stealth]
BTN_TRIGGER_HAPPY1 = BTN_NORTH
""")

    def test_cycle_advances(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        self.assertEqual(mgr.active_layer, "base")
        mgr.cycle_layer()
        self.assertEqual(mgr.active_layer, "combat")
        mgr.cycle_layer()
        self.assertEqual(mgr.active_layer, "stealth")

    def test_cycle_wraps(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        mgr.cycle_layer(); mgr.cycle_layer(); mgr.cycle_layer()
        self.assertEqual(mgr.active_layer, "base")

    def test_cycle_returns_name(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        self.assertEqual(mgr.cycle_layer(), "combat")

    def test_cycle_no_layers_returns_none(self):
        mgr = _mgr_from_ini("[profile.GAME]\n")
        mgr.switch("GAME")
        self.assertIsNone(mgr.cycle_layer())

    def test_effective_map_updates_on_cycle(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        self.assertEqual(mgr.effective_button_map[P1], P1)  # base: pass-through
        mgr.cycle_layer()
        self.assertEqual(mgr.effective_button_map[P1], A)   # combat: P1→A
        mgr.cycle_layer()
        self.assertEqual(mgr.effective_button_map[P1], X)   # stealth: P1→X


class TestSwitchLayer(unittest.TestCase):

    def _mgr(self) -> ProfileManager:
        return _mgr_from_ini(f"""
[profile.GAME]
[profile.GAME.layers]
switch_button = BTN_TRIGGER_HAPPY3
stack = base,combat
[profile.GAME.layer.base]
[profile.GAME.layer.combat]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
""")

    def test_switch_layer_direct(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        mgr.switch_layer("combat")
        self.assertEqual(mgr.active_layer, "combat")
        self.assertEqual(mgr.effective_button_map[P1], A)

    def test_switch_layer_unknown_raises(self):
        mgr = self._mgr()
        mgr.switch("GAME")
        with self.assertRaises(KeyError):
            mgr.switch_layer("nope")

    def test_switch_layer_on_layerless_profile_raises(self):
        mgr = _mgr_from_ini("[profile.GAME]\n")
        mgr.switch("GAME")
        with self.assertRaises(KeyError):
            mgr.switch_layer("anything")


class TestProfileSwitchResetsLayer(unittest.TestCase):

    def test_layer_resets_on_profile_switch(self):
        mgr = _mgr_from_ini(f"""
[profile.GAME]
[profile.GAME.layers]
switch_button = BTN_TRIGGER_HAPPY3
stack = base,combat
[profile.GAME.layer.base]
[profile.GAME.layer.combat]
BTN_TRIGGER_HAPPY1 = BTN_SOUTH
""")
        mgr.switch("GAME")
        mgr.cycle_layer()
        self.assertEqual(mgr.active_layer, "combat")
        mgr.switch("default")
        mgr.switch("GAME")
        self.assertEqual(mgr.active_layer, "base")


if __name__ == "__main__":
    unittest.main()
