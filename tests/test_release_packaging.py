"""Release version and AppImage builder regression tests."""
from __future__ import annotations

import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from preen_tool import __version__


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_app_package_and_debian_versions_match(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project = text.split("[project]", 1)[1].split("[", 1)[0]
        version = re.search(r'^version\s*=\s*"([^"\n]+)"', project, re.M)
        self.assertIsNotNone(version)
        self.assertEqual(version.group(1), __version__)
        debian = (ROOT / "debian/changelog").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(debian, "preen ({}) stable; urgency=medium".format(__version__))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [{}]".format(__version__), changelog)


class AppImageBuilderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout"
        shutil.copytree(ROOT, self.checkout,
                        ignore=shutil.ignore_patterns(".git", "dist", "build", "sdist", "__pycache__",
                                                      "*.egg-info", ".pytest_cache", ".venv"))

    def run_builder(self, tool):
        env = os.environ.copy()
        env["APPIMAGETOOL"] = str(tool)
        return subprocess.run(["bash", "packaging/build_appimage.sh"], cwd=self.checkout,
                              env=env, text=True, capture_output=True, timeout=30)

    def test_tool_that_produces_no_image_is_not_reported_as_a_success(self):
        tool = self.root / "tool"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        result = self.run_builder(tool)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not create an executable artifact", result.stderr)
        self.assertNotIn("Built and smoke-tested", result.stdout)
        self.assertFalse((self.checkout / "dist" / f"Preen-{__version__}-x86_64.AppImage").exists())

    def test_tool_that_produces_a_non_appimage_is_rejected(self):
        tool = self.root / "tool"
        tool.write_text('#!/bin/sh\nprintf invalid > "$3"\nchmod +x "$3"\n', encoding="utf-8")
        tool.chmod(0o755)
        result = self.run_builder(tool)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid type-2 AppImage header", result.stderr)
        self.assertFalse((self.checkout / "dist" / f"Preen-{__version__}-x86_64.AppImage").exists())

    def test_missing_explicit_tool_does_not_trigger_a_download(self):
        result = self.run_builder(self.root / "missing-tool")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APPIMAGETOOL is not executable", result.stderr)
        self.assertNotIn("Downloading appimagetool", result.stdout)


class ReleaseBuilderTests(unittest.TestCase):
    def test_source_deb_and_wheel_are_built_into_the_requested_directory(self):
        git = shutil.which("git")
        if not git or not shutil.which("dpkg-deb") or not shutil.which("sha256sum"):
            self.skipTest("git, dpkg-deb and sha256sum are needed")
        if importlib.util.find_spec("setuptools") is None or importlib.util.find_spec("wheel") is None:
            self.skipTest("setuptools and wheel are needed")
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            checkout = temp / "checkout"
            shutil.copytree(ROOT, checkout,
                            ignore=shutil.ignore_patterns(".git", "dist", "build", "sdist",
                                                          "__pycache__", "*.egg-info", ".venv"))
            # An isolated source copy has no .git; simulate the clean/tree
            # checks and delegate only git archive to the real checkout.
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/bin/sh\ncase \"$1\" in\n"
                "  status) exit 0;;\n"
                "  rev-parse) echo release-test-tree;;\n"
                "  archive) shift; exec {} -C {} archive \"$@\";;\n"
                "  *) exit 2;;\nesac\n".format(shlex.quote(git), shlex.quote(str(ROOT))),
                encoding="utf-8")
            fake_git.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            destination = temp / "release"
            result = subprocess.run(["bash", "packaging/build_release.sh", "--skip-appimage",
                                     str(destination)], cwd=checkout, env=env, text=True,
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout[-5000:] + result.stderr[-5000:])
            expected = {f"preen-{__version__}-source.zip", f"preen-{__version__}.tar.gz",
                        f"preen-{__version__}-py3-none-any.whl", f"preen_{__version__}_all.deb",
                        "SHA256SUMS"}
            self.assertEqual({path.name for path in destination.iterdir()}, expected)
            self.assertIn("AppImage skipped", result.stderr)
            subprocess.run(["sha256sum", "--check", "SHA256SUMS"], cwd=destination,
                           check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
