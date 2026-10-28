"""Theme integration against a stateful fake GNOME settings service."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from preen_tool.backend import ui_customization as look, utils
from tests.fakes import FakeSystem


class ThemeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = FakeSystem(Path(self.tmp.name))
        env = self.system.env()
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)
        utils.set_simulate(False)
        self.addCleanup(utils.set_simulate, False)
        self.themes = mock.patch.object(
            look, "_installed_themes",
            return_value={"Adwaita", "Adwaita-dark", "Yaru", "Yaru-dark",
                          "ZorinBlue-Light", "ZorinBlue-Dark"})
        self.themes.start()
        self.addCleanup(self.themes.stop)

    def values(self):
        return json.loads(self.system.state_path.read_text(encoding="utf-8"))["gsettings"]

    def test_modern_desktop_switches_dark_and_light_and_reads_back(self):
        self.system.update(gsettings={"gtk-theme": "Yaru", "color-scheme": "default"})
        self.assertTrue(look.apply_theme_mode("dark").ok)
        self.assertEqual(self.values()["color-scheme"], "prefer-dark")
        self.assertEqual(self.values()["gtk-theme"], "Yaru-dark")
        self.assertEqual(look.get_theme_mode(), "dark")
        self.assertTrue(look.apply_theme_mode("light").ok)
        self.assertEqual(self.values()["color-scheme"], "default")
        self.assertEqual(self.values()["gtk-theme"], "Yaru")
        self.assertEqual(look.get_theme_mode(), "light")

    def test_legacy_gnome_without_color_scheme_uses_installed_gtk_variant(self):
        self.system.update(gsettings_keys=["gtk-theme"],
                           gsettings={"gtk-theme": "ZorinBlue-Light"})
        outcome = look.apply_theme_mode("dark")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(self.values()["gtk-theme"], "ZorinBlue-Dark")
        self.assertEqual(look.get_theme_mode(), "dark")
        self.assertTrue(look.apply_theme_mode("light").ok)
        self.assertEqual(self.values()["gtk-theme"], "ZorinBlue-Light")
        self.assertEqual(look.get_theme_mode(), "light")

    def test_modern_scheme_works_if_legacy_gtk_theme_key_is_absent(self):
        self.system.update(gsettings_keys=["color-scheme"],
                           gsettings={"color-scheme": "default"})
        self.assertTrue(look.apply_theme_mode("dark").ok)
        self.assertEqual(self.values()["color-scheme"], "prefer-dark")
        self.assertEqual(look.get_theme_mode(), "dark")

    def test_theme_failure_is_reported_instead_of_false_success(self):
        self.system.update(gsettings_fail_set="color-scheme")
        outcome = look.apply_theme_mode("dark")
        self.assertFalse(outcome.ok)
        self.assertIn("color-scheme", " ".join([outcome.message] + outcome.details))
        self.assertEqual(self.values(), {})

    def test_unreadable_current_gtk_theme_does_not_get_replaced_by_a_guess(self):
        self.system.update(gsettings_fail_get="gtk-theme")
        result = look.apply_theme_mode("dark")
        self.assertFalse(result.ok)
        self.assertIn("Could not read", result.message)
        self.assertFalse(self.system.mutating_commands())

    def test_partial_write_failure_reports_scheme_changed(self):
        self.system.update(gsettings={"gtk-theme": "Adwaita", "color-scheme": "default"},
                           gsettings_fail_set="gtk-theme")
        result = look.apply_theme_mode("dark")
        self.assertFalse(result.ok)
        self.assertIn("Color scheme changed", result.message)
        self.assertEqual(self.values()["color-scheme"], "prefer-dark")
        self.assertEqual(self.values()["gtk-theme"], "Adwaita")

    def test_no_supported_theme_key_is_a_failure(self):
        self.system.update(gsettings_keys=[])
        self.assertFalse(look.apply_theme_mode("dark").ok)
        self.assertEqual(self.values(), {})

    def test_simulation_previews_both_settings_without_writing(self):
        self.system.update(gsettings={"gtk-theme": "Adwaita", "color-scheme": "default"})
        before = self.values()
        utils.set_simulate(True)
        log = mock.Mock()
        outcome = look.apply_theme_mode("dark", log=log)
        self.assertTrue(outcome.ok)
        self.assertEqual(self.values(), before)
        self.assertFalse(self.system.mutating_commands())
        logged = "".join(call.args[0] for call in log.append.call_args_list)
        self.assertIn("color-scheme", logged)
        self.assertIn("gtk-theme", logged)

    def test_unreadable_state_is_not_reported_as_light(self):
        with mock.patch.object(look, "has_command", return_value=False):
            self.assertIsNone(look.get_theme_mode())

    def test_explicit_light_preference_is_read_as_light(self):
        self.system.update(gsettings={"gtk-theme": "Adwaita-dark", "color-scheme": "prefer-light"})
        self.assertEqual(look.get_theme_mode(), "light")

    def test_builtin_adwaita_variants_are_available_without_theme_directories(self):
        self.themes.stop()
        with mock.patch.object(look, "_theme_roots", return_value=[]):
            self.assertIn("Adwaita", look._installed_themes())
            self.assertIn("Adwaita-dark", look._installed_themes())


if __name__ == "__main__":
    unittest.main()
