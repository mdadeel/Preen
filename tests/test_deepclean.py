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

    def test_unavailable_is_not_zero(self):
        self.assertEqual(deepclean.format_size(None), "Unavailable")


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

    def test_scan_estimates_only_usage_above_retention_and_reports_unknown(self):
        with mock.patch.object(deepclean, "_journal_size", return_value=350 * 1024 ** 2):
            journal = next(item for item in deepclean.scan_cleanable() if item["key"] == "journal")
        self.assertEqual(journal["size"], 250 * 1024 ** 2)
        with mock.patch.object(deepclean, "_journal_size", return_value=None):
            journal = next(item for item in deepclean.scan_cleanable() if item["key"] == "journal")
        self.assertIsNone(journal["size"])
        with mock.patch.object(utils, "has_command", return_value=True), \
                mock.patch.object(utils, "run_cmd", return_value=utils.CommandResult(1, "", "denied")):
            self.assertIsNone(deepclean._journal_size())

    def test_vacuum_failure_is_propagated_and_never_called_success(self):
        with mock.patch.object(utils, "run_cmd",
                               return_value=utils.CommandResult(17, "", "permission denied")):
            outcome = deepclean.vacuum_journal()
        self.assertFalse(outcome.ok)
        self.assertIn("Could not vacuum", outcome.message)
        self.assertIn("exit 17", " ".join(outcome.details))
        self.assertIn("permission denied", " ".join(outcome.details))


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

    def test_unreadable_tree_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(deepclean.os, "walk", side_effect=PermissionError("denied")):
            self.assertIsNone(deepclean.du_size(tmp))


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

    def test_symlink_clean_root_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(utils, "is_simulate", return_value=False):
            outside = Path(tmp) / "outside"
            outside.mkdir()
            marker = outside / "important"
            marker.write_text("keep", encoding="utf-8")
            link = Path(tmp) / "cache-link"
            link.symlink_to(outside, target_is_directory=True)
            with mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": str(link)}):
                self.assertIsNone(deepclean.du_size(str(link)))
                outcome = deepclean.clean_user_paths(["trash"])
            self.assertFalse(outcome.ok)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_trash_cleanup_removes_only_matching_metadata_after_deletion(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(utils, "is_simulate", return_value=False):
            root = Path(tmp)
            files, info = root / "files", root / "info"
            files.mkdir()
            info.mkdir()
            (files / "item.txt").write_text("trash", encoding="utf-8")
            (info / "item.txt.trashinfo").write_text("metadata", encoding="utf-8")
            (info / "other.trashinfo").write_text("keep", encoding="utf-8")
            with mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": str(files)}):
                self.assertTrue(deepclean.clean_user_paths(["trash"]).ok)
            self.assertFalse((info / "item.txt.trashinfo").exists())
            self.assertTrue((info / "other.trashinfo").exists())

    def test_trash_metadata_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(utils, "is_simulate", return_value=False):
            root = Path(tmp)
            files, outside = root / "files", root / "outside"
            files.mkdir()
            outside.mkdir()
            (files / "item").write_text("trash", encoding="utf-8")
            marker = outside / "item.trashinfo"
            marker.write_text("keep", encoding="utf-8")
            (root / "info").symlink_to(outside, target_is_directory=True)
            with mock.patch.dict(deepclean.USER_CLEAN_PATHS, {"trash": str(files)}):
                outcome = deepclean.clean_user_paths(["trash"])
            self.assertFalse(outcome.ok)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_missing_dir_is_not_an_error(self):
        with mock.patch.dict(deepclean.USER_CLEAN_PATHS,
                             {"thumbnails": "/nonexistent/x"}), \
                mock.patch.object(utils, "is_simulate", return_value=False):
            self.assertTrue(deepclean.clean_user_paths(["thumbnails"]).ok)


class ScanContentsTest(unittest.TestCase):
    def test_pip_cache_is_a_known_user_cleanable(self):
        self.assertIn("pip_cache", deepclean.USER_CLEAN_PATHS)
        self.assertIn("pip_cache", deepclean.USER_CLEAN_INFO)
        keys = {item["key"] for item in deepclean.scan_cleanable()}
        self.assertEqual(
            keys, {"apt_cache", "journal", "thumbnails", "pip_cache", "trash"})

    def test_pip_cache_is_grouped_with_other_user_cleans(self):
        actions = deepclean.build_clean_actions([
            {"key": "pip_cache", "root": False},
            {"key": "thumbnails", "root": False},
        ])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0][2], (["pip_cache", "thumbnails"],))


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
