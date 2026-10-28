"""Preen-only appearance and read-only desktop detection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from preen_tool.backend import settings, ui_customization as look, utils
from tests.fakes import FakeSystem


class ThemeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = FakeSystem(Path(self.tmp.name))
        env = self.system.env()
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)
        config = Path(self.tmp.name) / "preen"
        for name, value in (("CONFIG_DIR", str(config)),
                            ("SETTINGS_PATH", str(config / "settings.json"))):
            patch = mock.patch.object(settings, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        utils.set_simulate(False)
        self.addCleanup(utils.set_simulate, False)

    def values(self):
        return json.loads(self.system.state_path.read_text(encoding="utf-8"))["gsettings"]

    def test_light_dark_and_system_are_persisted_without_desktop_writes(self):
        self.system.update(gsettings={"gtk-theme": "Yaru", "color-scheme": "default",
                                      "icon-theme": "Yaru"})
        before = self.values()
        self.assertTrue(settings.set_value("default_source", "apt"))
        for mode in ("dark", "light", "system"):
            with self.subTest(mode=mode):
                result = look.apply_theme_mode(mode)
                self.assertTrue(result.ok, result.message)
                self.assertIn("Desktop theme unchanged", result.message)
                self.assertEqual(settings.load()["appearance_mode"], mode)
                self.assertEqual(settings.load()["default_source"], "apt")
                self.assertEqual(self.values(), before)
        self.assertFalse(self.system.mutating_commands())
        self.assertFalse(self.system.commands())  # no gsettings dependency even for explicit choices

    def test_simulation_does_not_save_preference_or_touch_desktop(self):
        self.system.update(gsettings={"gtk-theme": "Adwaita", "color-scheme": "default"})
        self.assertTrue(settings.set_value("appearance_mode", "light"))
        before = Path(settings.SETTINGS_PATH).read_bytes(), self.values()
        utils.set_simulate(True)
        log = mock.Mock()
        outcome = look.apply_theme_mode("dark", log=log)
        self.assertTrue(outcome.ok)
        self.assertEqual((Path(settings.SETTINGS_PATH).read_bytes(), self.values()), before)
        self.assertFalse(self.system.mutating_commands())
        logged = "".join(call.args[0] for call in log.append.call_args_list)
        self.assertIn("Preen appearance", logged)
        self.assertIn("desktop unchanged", logged)

    def test_invalid_mode_and_write_failure_are_reported(self):
        for invalid in ("neon", None, 42):
            self.assertFalse(look.apply_theme_mode(invalid).ok)
        with mock.patch.object(settings, "set_value", return_value=False):
            result = look.apply_theme_mode("dark")
        self.assertFalse(result.ok)
        self.assertIn("Could not save", result.message)
        self.assertFalse(self.system.mutating_commands())

    def test_follow_system_detects_modern_and_legacy_gnome_read_only(self):
        self.system.update(gsettings={"gtk-theme": "Yaru", "color-scheme": "prefer-dark"})
        self.assertEqual(look.get_theme_mode(), "dark")
        self.system.update(gsettings={"gtk-theme": "Yaru-dark", "color-scheme": "prefer-light"})
        self.assertEqual(look.get_theme_mode(), "light")
        self.system.update(gsettings_keys=["gtk-theme"],
                           gsettings={"gtk-theme": "ZorinBlue-Dark"})
        self.assertEqual(look.get_theme_mode(), "dark")
        self.system.update(gsettings={"gtk-theme": "ZorinBlue-Light"})
        self.assertEqual(look.get_theme_mode(), "light")
        self.assertFalse(self.system.mutating_commands())

    def test_unreadable_desktop_is_not_falsely_reported_as_light(self):
        with mock.patch.object(look, "has_command", return_value=False):
            self.assertIsNone(look.get_theme_mode())
        self.system.update(gsettings_fail_get="color-scheme", gsettings_keys=["color-scheme"])
        self.assertIsNone(look.get_theme_mode())


if __name__ == "__main__":
    unittest.main()
