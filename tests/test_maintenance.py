"""Tests for the maintenance scheduler backend (preen-maintenance.timer)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from preen_tool.backend import maintenance, utils  # noqa: E402
from tests.fakes import FakeSystem  # noqa: E402


class ListLog:
    def __init__(self):
        self.lines = []

    def append(self, text):
        self.lines.append(str(text))

    def text(self):
        return "".join(self.lines)


class MaintenanceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = FakeSystem(self.root)
        env_ctx = self.fake.env()
        env_ctx.__enter__()
        self.addCleanup(env_ctx.__exit__, None, None, None)
        utils.set_simulate(False)
        self.addCleanup(utils.set_simulate, False)
        self.log = ListLog()

    def test_get_schedule_reports_absent_units(self):
        with mock.patch.object(maintenance, "TIMER_PATH",
                               str(self.root / "absent.timer")):
            schedule = maintenance.get_schedule()
        self.assertEqual(schedule, {"installed": False, "enabled": False,
                                    "frequency": "", "calendar": ""})

    def test_get_schedule_reads_calendar_and_enabled_state(self):
        timer = self.root / "preen-maintenance.timer"
        timer.write_text("[Timer]\nOnCalendar=Sun *-*-* 12:00:00\nPersistent=true\n",
                         encoding="utf-8")
        with mock.patch.object(maintenance, "TIMER_PATH", str(timer)), \
                mock.patch.object(maintenance, "run_cmd",
                                  return_value=utils.CommandResult(0, "enabled\n", "")):
            schedule = maintenance.get_schedule()
        self.assertTrue(schedule["installed"])
        self.assertTrue(schedule["enabled"])
        self.assertEqual(schedule["frequency"], "weekly")

    def test_get_schedule_flags_unknown_calendars_as_custom(self):
        timer = self.root / "preen-maintenance.timer"
        timer.write_text("[Timer]\nOnCalendar=Sat *-*-1..7 09:00:00\n", encoding="utf-8")
        with mock.patch.object(maintenance, "TIMER_PATH", str(timer)):
            schedule = maintenance.get_schedule()
        self.assertEqual(schedule["frequency"], "custom")
        self.assertEqual(schedule["enabled"], False)

    def test_set_schedule_writes_units_and_starts_timer(self):
        outcome = maintenance.set_schedule(True, "weekly", log=self.log)
        self.assertTrue(outcome.ok)
        entry = self.fake.mutating_commands()[-1]
        self.assertEqual(entry["cmd"], "pkexec")
        script = entry["args"][2]
        self.assertIn("OnCalendar=Sun *-*-* 12:00:00", script)
        self.assertIn("Persistent=true", script)
        self.assertIn("systemctl enable --now preen-maintenance.timer", script)
        self.assertIn("journalctl --vacuum-size=100M", script)
        self.assertIn("flatpak uninstall --unused -y --noninteractive", script)

    def test_set_schedule_removal_disables_and_deletes_units(self):
        outcome = maintenance.set_schedule(False, "weekly", log=self.log)
        self.assertTrue(outcome.ok)
        script = self.fake.mutating_commands()[-1]["args"][2]
        self.assertIn("systemctl disable --now preen-maintenance.timer", script)
        self.assertIn("rm -f", script)
        self.assertIn("systemctl daemon-reload", script)

    def test_set_schedule_rejects_unknown_frequency(self):
        outcome = maintenance.set_schedule(True, "hourly", log=self.log)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.fake.mutating_commands(), [])

    def test_simulate_mode_previews_the_schedule_without_changes(self):
        utils.set_simulate(True)
        outcome = maintenance.set_schedule(True, "daily", log=self.log)
        self.assertTrue(outcome.ok)
        self.assertIn("Would schedule", outcome.message)
        self.assertIn("OnCalendar=*-*-* 12:00:00", self.log.text())
        self.assertEqual(self.fake.mutating_commands(), [])


if __name__ == "__main__":
    unittest.main()
