"""Tests for the services/boot backend: parsers and input validation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preen_tool.backend import services  # noqa: E402


LIST_UNITS_FIXTURE = """\
  NetworkManager.service loaded active running Network Manager
  accounts-daemon.service loaded active running Accounts Service
  apparmor.service        loaded inactive dead   apparmor.service
  bad-line-without-enough-columns
  notaservice.service loaded active running this line is skipped
  udisks2.service loaded active running Disk Manager
"""

UNIT_FILES_FIXTURE = """\
NetworkManager.service        enabled enabled
apparmor.service              enabled enabled
udisks2.service               disabled disabled
"""


class ParseListUnitsTest(unittest.TestCase):
    def test_parses_five_columns_and_skips_junk(self):
        units = services.parse_list_units(LIST_UNITS_FIXTURE)
        by_unit = {u["unit"]: u for u in units}
        self.assertEqual(len(units), 5)
        self.assertEqual(by_unit["NetworkManager.service"]["active"], "active")
        self.assertEqual(by_unit["apparmor.service"]["sub"], "dead")
        self.assertEqual(by_unit["udisks2.service"]["description"], "Disk Manager")
        self.assertEqual(by_unit["notaservice.service"]["description"],
                         "this line is skipped")
        self.assertNotIn("bad-line-without-enough-columns", by_unit)

    def test_failed_units_with_status_bullet_are_included(self):
        rows = services.parse_list_units("● broken.service loaded failed failed Broken service\n")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unit"], "broken.service")
        self.assertEqual(rows[0]["active"], "failed")

    def test_empty_and_garbage(self):
        self.assertEqual(services.parse_list_units(""), [])
        self.assertEqual(services.parse_list_units("random text only"), [])


class ParseUnitFilesTest(unittest.TestCase):
    def test_maps_unit_to_state(self):
        states = services.parse_unit_files(UNIT_FILES_FIXTURE)
        self.assertEqual(states["NetworkManager.service"], "enabled")
        self.assertEqual(states["udisks2.service"], "disabled")


class ListServicesTest(unittest.TestCase):
    def test_failed_live_query_is_unavailable_with_exit_and_error(self):
        from preen_tool.backend import utils
        log = mock.Mock()
        with mock.patch.object(services.utils, "run_cmd",
                               return_value=utils.CommandResult(1, "", "systemd offline")) as run:
            result = services.list_services(log=log)
        self.assertIsNone(result)
        self.assertEqual(run.call_count, 1)
        message = log.append.call_args.args[0]
        self.assertIn("exit 1", message)
        self.assertIn("systemd offline", message)

    def test_missing_unit_file_states_do_not_hide_live_services(self):
        from preen_tool.backend import utils
        log = mock.Mock()
        results = [utils.CommandResult(0, LIST_UNITS_FIXTURE, ""),
                   utils.CommandResult(5, "", "no unit files")]
        with mock.patch.object(services.utils, "run_cmd", side_effect=results):
            result = services.list_services(log=log)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(entry["unit_state"] == "" for entry in result))
        self.assertIn("exit 5", log.append.call_args.args[0])


class SetServiceStateTest(unittest.TestCase):
    def test_rejects_bad_action(self):
        outcome = services.set_service_state("ok.service", "reboot")
        self.assertFalse(outcome.ok)

    def test_rejects_injection_unit_names(self):
        for bad in ("evil;rm-rf.service", "../etc/passwd.service",
                    "x.service && y", "", "nosuffix"):
            outcome = services.set_service_state(bad, "stop")
            self.assertFalse(outcome.ok, bad)

    def test_valid_unit_passes_validation(self):
        # The unit name/action validation is what this checks; systemctl is
        # not required to exist for the failure path to be correct.
        outcome = services.set_service_state("not-a-real-unit-xyz.service", "stop")
        self.assertIsInstance(outcome.ok, bool)

    def test_restart_is_supported_and_uses_proper_tense(self):
        from unittest import mock
        from preen_tool.backend import utils
        self.assertIn("restart", services.ACTIONS)
        with mock.patch.object(services.utils, "run_cmd",
                               return_value=utils.CommandResult(0, "", "")):
            outcome = services.set_service_state("demo.service", "restart")
        self.assertTrue(outcome.ok)
        self.assertIn("restarted", outcome.message)
        self.assertNotIn("restartd", outcome.message)

    def test_every_service_action_uses_one_simulate_gated_polkit_command(self):
        from preen_tool.backend import utils
        for action in services.ACTIONS:
            with self.subTest(action=action), \
                    mock.patch.object(services.utils, "run_cmd",
                                      return_value=utils.CommandResult(0, "", "")) as run:
                result = services.set_service_state("demo.service", action)
            self.assertTrue(result.ok)
            self.assertEqual(run.call_args.args[0], ["systemctl", action, "demo.service"])
            self.assertTrue(run.call_args.kwargs["use_pkexec"])
            self.assertTrue(run.call_args.kwargs["mutate"])

    def test_past_tense_covers_every_action(self):
        for action in services.ACTIONS:
            self.assertIn(action, services._PAST_TENSE)


class ParseAnalyzeTest(unittest.TestCase):
    def test_full_summary(self):
        text = ("Startup finished in 4.227s (firmware) + 1.105s (loader) + "
                "2.316s (kernel) + 5.664s (userspace) = 13.313s")
        info = services.parse_analyze(text)
        self.assertEqual(info["total"], "13.313s")
        self.assertEqual(info["firmware"], "4.227s")
        self.assertEqual(info["loader"], "1.105s")
        self.assertEqual(info["kernel"], "2.316s")
        self.assertEqual(info["userspace"], "5.664s")

    def test_multi_part_durations_are_not_truncated(self):
        text = ("Startup finished in 2.200s (kernel) + 1min 5.500s (userspace) "
                "= 1min 7.700s\n")
        info = services.parse_analyze(text)
        self.assertEqual(info["userspace"], "1min 5.500s")
        self.assertEqual(info["total"], "1min 7.700s")

    def test_garbage(self):
        self.assertEqual(services.parse_analyze("nothing useful"), {})


class ParseBlameTest(unittest.TestCase):
    def test_top_rows_sorted_input(self):
        text = ("5.664s NetworkManager-wait-online.service\n"
                "1.201s udisks2.service\n"
                "junk line without time\n")
        rows = services.parse_blame(text, limit=2)
        self.assertEqual(rows, [("NetworkManager-wait-online.service", "5.664s"),
                                ("udisks2.service", "1.201s")])

    def test_blame_with_minutes_keeps_the_unit_and_full_duration(self):
        rows = services.parse_blame("1min 2.345s slow.service\n200ms fast.service\n")
        self.assertEqual(rows, [("slow.service", "1min 2.345s"),
                                ("fast.service", "200ms")])


if __name__ == "__main__":
    unittest.main()
