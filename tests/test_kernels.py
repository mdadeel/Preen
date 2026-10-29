"""Tests for preen_tool.backend.kernels (old-kernel cleanup)."""
import os
import unittest
from unittest import mock

from preen_tool.backend import deepclean, kernels

INSTALLED_LINES = """
linux-image-6.11.0-19-generic
linux-modules-6.11.0-19-generic
linux-modules-extra-6.11.0-19-generic
linux-headers-6.11.0-19-generic
linux-image-6.8.0-45-generic
linux-modules-6.8.0-45-generic
linux-image-5.15.0-42-generic
linux-image-generic
linux-headers-generic
linux-generic
""".strip().splitlines()


class ParseTest(unittest.TestCase):
    def test_groups_by_version_and_skips_meta_packages(self):
        groups = kernels.parse_installed_kernels(INSTALLED_LINES)
        self.assertEqual(
            sorted(groups),
            ["5.15.0-42-generic", "6.11.0-19-generic", "6.8.0-45-generic"])
        self.assertEqual(
            sorted(groups["6.11.0-19-generic"]),
            ["linux-headers-6.11.0-19-generic", "linux-image-6.11.0-19-generic",
             "linux-modules-6.11.0-19-generic",
             "linux-modules-extra-6.11.0-19-generic"])

    def test_garbage_lines_are_ignored(self):
        self.assertEqual(kernels.parse_installed_kernels(
            ["", "random-output", "linux-image"]), {})


class SelectRemovableTest(unittest.TestCase):
    def setUp(self):
        self.groups = kernels.parse_installed_kernels(INSTALLED_LINES)

    def test_keeps_running_and_one_spare(self):
        removable = kernels.select_removable(
            self.groups, running="6.11.0-19-generic", keep=1)
        self.assertEqual(removable, ["linux-image-5.15.0-42-generic"])

    def test_keep_zero_removes_everything_but_running(self):
        removable = kernels.select_removable(
            self.groups, running="6.11.0-19-generic", keep=0)
        self.assertEqual(
            sorted(removable),
            ["linux-image-5.15.0-42-generic", "linux-image-6.8.0-45-generic",
             "linux-modules-6.8.0-45-generic"])

    def test_running_kernel_is_never_removable(self):
        removable = kernels.select_removable(self.groups, running="5.15.0-42-generic")
        self.assertNotIn("linux-image-5.15.0-42-generic", removable)
        self.assertIn("linux-image-6.8.0-45-generic", removable)

    def test_unknown_running_release_keeps_the_newest(self):
        removable = kernels.select_removable(self.groups, running="9.9.9-custom")
        self.assertNotIn("linux-image-6.11.0-19-generic", removable)
        self.assertIn("linux-image-5.15.0-42-generic", removable)


class DeepCleanIntegrationTest(unittest.TestCase):
    def test_scan_includes_the_old_kernels_item(self):
        with mock.patch.object(kernels, "reclaimable_bytes", return_value=250 * 1024 ** 2):
            items = {item["key"]: item for item in deepclean.scan_cleanable()}
        self.assertIn("old_kernels", items)
        self.assertTrue(items["old_kernels"]["root"])
        self.assertEqual(items["old_kernels"]["size"], 250 * 1024 ** 2)

    def test_clean_actions_route_old_kernels_to_the_kernel_module(self):
        actions = deepclean.build_clean_actions(
            [{"key": "old_kernels", "root": True}])
        self.assertEqual(len(actions), 1)
        label, func, args = actions[0]
        self.assertEqual(label, "Old kernels")
        self.assertIs(func, kernels.remove_old_kernels)

    def test_failure_reports_as_unknown_size(self):
        with mock.patch.object(kernels, "reclaimable_bytes", return_value=None):
            items = {item["key"]: item for item in deepclean.scan_cleanable()}
        self.assertIsNone(items["old_kernels"]["size"])


if __name__ == "__main__":
    unittest.main()
