"""Tests for the deep-clean backend: parsers, simulate gating, deletion."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preen_tool.backend import deepclean, utils  # noqa: E402


class FormatSizeTest(unittest.TestCase):
    def test_known_sizes(self):
        self.assertEqual(deepclean.format_size(0), "0 B")
        self.assertEqual(deepclean.format_size(512), "512 B")
        self.assertEqual(deepclean.format_size(1024), "1.0 KB")
        self.assertEqual(deepclean.format_size(1.2 * 1024 ** 3), "1.2 GB")

    def test_negative_is_clamped(self):
        self.assertEqual(deepclean.format_size(-5), "0 B")


class JournalUsageTest(unittest.TestCase):
    def test_gigabytes(self):
        text = "Archived and active journals take up 1.2G in the file system."
        self.assertEqual(deepclean.parse_journal_usage(text), int(1.2 * 1024 ** 3))

    def test_megabytes_and_bytes(self):
        self.assertEqual(deepclean.parse_journal_usage("take up 500.0M"), 500 * 1024 ** 2)
        self.assertEqual(deepclean.parse_journal_usage("take up 8B"), 8)

    def test_garbage_returns_zero(self):
        self.assertEqual(deepclean.parse_journal_usage("no numbers here"), 0)
        self.assertEqual(deepclean.parse_journal_usage(""), 0)


class DuSizeTest(unittest.TestCase):
    def test_sums_files_and_tolerates_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.bin"), "wb") as handle:
                handle.write(b"x" * 100)
            os.makedirs(os.path.join(tmp, "sub"))
            with open(os.path.join(tmp, "sub", "b.bin"), "wb") as handle:
                handle.write(b"x" * 50)
            self.assertEqual(deepclean.du_size(tmp), 150)
        self.assertEqual(deepclean.du_size("/nonexistent/path/xyz"), 0)


class CleanUserPathsTest(unittest.TestCase):
    def _make_junk(self, tmp):
        sub = os.path.join(tmp, "subdir")
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(tmp, "file.txt"), "w") as handle:
            handle.write("junk")
        with open(os.path.join(sub, "nested.txt"), "w") as handle:
            handle.write("junk")

    def test_simulate_mode_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": tmp}), \
                mock.patch.object(utils, "is_simulate", return_value=True):
            self._make_junk(tmp)
            outcome = deepclean.clean_user_paths(["trash"])
            self.assertTrue(outcome.ok)
            self.assertTrue(os.path.exists(os.path.join(tmp, "file.txt")))

    def test_real_run_empties_contents_but_keeps_dir(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": tmp}), \
                mock.patch.object(utils, "is_simulate", return_value=False):
            self._make_junk(tmp)
            outcome = deepclean.clean_user_paths(["trash"])
            self.assertTrue(outcome.ok)
            self.assertEqual(os.listdir(tmp), [])

    def test_unknown_key_fails_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": tmp}), \
                mock.patch.object(utils, "is_simulate", return_value=False):
            self._make_junk(tmp)
            outcome = deepclean.clean_user_paths(["trash", "mystery-key"])
            self.assertFalse(outcome.ok)
            self.assertTrue(os.path.exists(os.path.join(tmp, "file.txt")))

    def test_missing_dir_is_not_an_error(self):
        with mock.patch.dict(deepclean.USER_CLEAN_PATHS,
                             {"thumbnails": "/nonexistent/x"}), \
                mock.patch.object(utils, "is_simulate", return_value=False):
            self.assertTrue(deepclean.clean_user_paths(["thumbnails"]).ok)


class BuildCleanActionsTest(unittest.TestCase):
    def test_root_items_get_own_steps_and_user_items_are_batched(self):
        actions = deepclean.build_clean_actions([
            {"key": "apt_cache", "root": True},
            {"key": "journal", "root": True},
            {"key": "thumbnails", "root": False},
            {"key": "trash", "root": False},
        ])
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0][0], "APT cache")
        self.assertEqual(actions[1][0], "System journal")
        self.assertEqual(actions[2][2], (["thumbnails", "trash"],))

    def test_nothing_selected(self):
        self.assertEqual(deepclean.build_clean_actions([]), [])


if __name__ == "__main__":
    unittest.main()
