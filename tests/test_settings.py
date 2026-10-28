"""Tests for persistent preferences."""
from __future__ import annotations

import json
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preen_tool.backend import settings  # noqa: E402


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "zorin-optimizer" / "settings.json"
        self.config_patch = mock.patch.object(settings, "CONFIG_DIR", str(self.path.parent))
        self.path_patch = mock.patch.object(settings, "SETTINGS_PATH", str(self.path))
        self.config_patch.start()
        self.path_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.addCleanup(self.path_patch.stop)

    def test_defaults_are_returned_when_no_file_exists(self):
        values = settings.load()
        self.assertFalse(values["simulate_on_startup"])
        self.assertEqual(values["default_source"], "flatpak")
        self.assertEqual(values["appearance_mode"], "system")
        self.assertTrue(values["confirm_destructive"])
        self.assertEqual(values["auto_refresh_seconds"], 15)
        self.assertEqual(values["page_on_startup"], "dashboard")

    def test_save_and_load_roundtrip_creates_parent_directory(self):
        values = settings.defaults()
        values.update({"default_source": "apt", "auto_refresh_seconds": 30,
                       "simulate_on_startup": True})
        self.assertTrue(settings.save(values))
        self.assertTrue(self.path.exists())
        loaded = settings.load()
        self.assertEqual(loaded["default_source"], "apt")
        self.assertEqual(loaded["auto_refresh_seconds"], 30)
        self.assertTrue(loaded["simulate_on_startup"])

    def test_corrupt_file_falls_back_to_defaults(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not valid json", encoding="utf-8")
        self.assertEqual(settings.load(), settings.defaults())

    def test_invalid_values_are_sanitised(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "default_source": "snap",
            "appearance_mode": "neon",
            "auto_refresh_seconds": 999999,
            "page_on_startup": "../../etc",
            "confirm_destructive": "yes",
            "unknown_key": "ignored",
        }), encoding="utf-8")
        values = settings.load()
        self.assertEqual(values["default_source"], "flatpak")
        self.assertEqual(values["appearance_mode"], "system")
        self.assertEqual(values["auto_refresh_seconds"], 15)
        self.assertEqual(values["page_on_startup"], "dashboard")
        self.assertIs(values["confirm_destructive"], True)
        self.assertNotIn("unknown_key", values)

    def test_save_is_atomic_and_leaves_no_temp_file(self):
        self.assertTrue(settings.save(settings.defaults()))
        self.assertFalse((self.path.parent / "settings.json.tmp").exists())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["default_source"],
                         "flatpak")

    def test_set_value_and_reset(self):
        self.assertTrue(settings.set_value("default_source", "apt"))
        self.assertEqual(settings.get("default_source"), "apt")
        self.assertTrue(settings.reset())
        self.assertEqual(settings.get("default_source"), "flatpak")

    def test_preference_updates_preserve_appearance(self):
        self.assertTrue(settings.set_value("appearance_mode", "dark"))
        self.assertTrue(settings.update({"default_source": "apt", "auto_refresh_seconds": 30}))
        self.assertEqual(settings.load()["appearance_mode"], "dark")
        self.assertEqual(settings.load()["default_source"], "apt")
        self.assertTrue(settings.reset())
        self.assertEqual(settings.get("appearance_mode"), "system")

    def test_concurrent_preference_updates_do_not_lose_unrelated_fields(self):
        barrier = threading.Barrier(3)
        results = []

        def update(key, value):
            barrier.wait()
            results.append(settings.set_value(key, value))

        threads = [threading.Thread(target=update, args=("appearance_mode", "dark")),
                   threading.Thread(target=update, args=("default_source", "apt"))]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, [True, True])
        self.assertEqual(settings.load()["appearance_mode"], "dark")
        self.assertEqual(settings.load()["default_source"], "apt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
