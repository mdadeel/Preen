"""Tests for the ubuntu-drivers backend (device parsing + installs)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from preen_tool.backend import drivers, utils  # noqa: E402
from tests.fakes import FakeSystem  # noqa: E402

SAMPLE_DEVICES_OUTPUT = """\
== cpu/microcode ==
vendor: Human
model: unknown modalias/cpu
driver: amd64-microcode - distro free recommended

== /sys/devices/pci0000:00/0000:01:00.0 ==
modalias: pci:v000010DEd00001C82sv00001458sd00003752bc03sc00i00
vendor: NVIDIA Corporation
model: GP104 [GeForce GTX 1070]
driver: nvidia-driver-535 - distro non-free recommended
driver: nvidia-driver-535-open - distro non-free open-gpu-kernel-modules
driver: xserver-xorg-video-nouveau - distro free builtin
"""


class ListLog:
    def __init__(self):
        self.lines = []

    def append(self, text):
        self.lines.append(str(text))

    def text(self):
        return "".join(self.lines)


class DriversParseTest(unittest.TestCase):
    def test_parse_devices_splits_sections_and_flags_recommended(self):
        devices = drivers.parse_devices(SAMPLE_DEVICES_OUTPUT)
        self.assertEqual(len(devices), 2)
        microcode, gpu = devices
        self.assertEqual(microcode["vendor"], "Human")
        self.assertEqual(microcode["packages"], [
            {"name": "amd64-microcode", "recommended": True, "note": "distro free recommended"},
        ])
        self.assertEqual(gpu["vendor"], "NVIDIA Corporation")
        names = [package["name"] for package in gpu["packages"]]
        self.assertEqual(names, ["nvidia-driver-535", "nvidia-driver-535-open",
                                 "xserver-xorg-video-nouveau"])
        self.assertEqual([package["recommended"] for package in gpu["packages"]],
                         [True, False, False])

    def test_parse_devices_ignores_garbage(self):
        self.assertEqual(drivers.parse_devices(""), [])
        self.assertEqual(drivers.parse_devices("not a section\ndriver: bad name here!"), [])


class DriversBackendTest(unittest.TestCase):
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

    def test_list_devices_reports_missing_tool(self):
        with mock.patch.object(drivers, "has_command", return_value=False):
            result = drivers.list_devices()
        self.assertFalse(result["available"])
        self.assertEqual(result["devices"], [])
        self.assertTrue(result["warnings"])

    def test_list_devices_parses_ubuntu_drivers_output(self):
        with mock.patch.object(drivers, "has_command", return_value=True), \
                mock.patch.object(drivers, "run_cmd",
                                  return_value=utils.CommandResult(0, SAMPLE_DEVICES_OUTPUT, "")):
            result = drivers.list_devices()
        self.assertTrue(result["available"])
        self.assertEqual(len(result["devices"]), 2)

    def test_list_devices_reports_command_failure(self):
        with mock.patch.object(drivers, "has_command", return_value=True), \
                mock.patch.object(drivers, "run_cmd",
                                  return_value=utils.CommandResult(2, "", "boom")):
            result = drivers.list_devices(log=self.log)
        self.assertTrue(result["available"])
        self.assertEqual(result["devices"], [])
        self.assertTrue(any("exit 2" in warning for warning in result["warnings"]))

    def test_install_driver_runs_polkit_gated_apt(self):
        outcome = drivers.install_driver(["nvidia-driver-535"], log=self.log)
        self.assertTrue(outcome.ok)
        entry = self.fake.mutating_commands()[-1]
        self.assertEqual(entry["cmd"], "pkexec")
        self.assertIn("apt-get install -y nvidia-driver-535", entry["args"][2])

    def test_install_driver_rejects_bad_and_empty_selections(self):
        self.assertFalse(drivers.install_driver([]).ok)
        self.assertFalse(drivers.install_driver(["bad name; rm -rf"]).ok)
        self.assertEqual(self.fake.mutating_commands(), [])

    def test_install_driver_simulates(self):
        utils.set_simulate(True)
        outcome = drivers.install_driver(["nvidia-driver-535"], log=self.log)
        self.assertTrue(outcome.ok)
        self.assertIn("Would install", outcome.message)
        self.assertIn("[simulate]", self.log.text())

    def test_autoinstall_uses_ubuntu_drivers_autoinstall(self):
        outcome = drivers.autoinstall(log=self.log)
        self.assertTrue(outcome.ok)
        self.assertIn("ubuntu-drivers autoinstall",
                      self.fake.mutating_commands()[-1]["args"][2])

    def test_autoinstall_needs_the_tool(self):
        with mock.patch.object(drivers, "has_command", return_value=False):
            outcome = drivers.autoinstall()
        self.assertFalse(outcome.ok)


if __name__ == "__main__":
    unittest.main()
