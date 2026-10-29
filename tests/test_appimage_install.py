"""Tests for packaging/install_appimage.sh and packaging/uninstall_appimage.sh.

The scripts run against a stub AppImage (a shell script implementing just
enough of the AppImage runtime) and a temporary HOME, so no root, GTK or
network is needed. System-scope installs need root and are not exercised
beyond the permission check.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "packaging" / "install_appimage.sh"
UNINSTALLER = REPO_ROOT / "packaging" / "uninstall_appimage.sh"

DESKTOP_ID = "io.github.mdadeel.Preen.desktop"

STUB_APPIMAGE = """#!/usr/bin/env bash
# Stub AppImage: supports --appimage-extract for the two entries the installer
# requests (the desktop file and the icon).
set -euo pipefail
[ "${1:-}" = "--appimage-extract" ] || exit 1
mkdir -p squashfs-root
if [ "$2" = "preen.png" ]; then
    printf 'png-bytes' > squashfs-root/preen.png
else
    cat > "squashfs-root/$2" <<'EOF'
[Desktop Entry]
Type=Application
Name=Preen
Exec=preen
Icon=preen
StartupWMClass=preen
EOF
fi
"""


def run_script(script, *args, home, extra_env=None):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = ""
    env["XDG_CONFIG_HOME"] = ""
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(script), *args], env=env, capture_output=True, text=True
    )


class ScriptSyntaxTest(unittest.TestCase):
    def test_scripts_parse(self):
        for script in (INSTALLER, UNINSTALLER):
            with self.subTest(script=script.name):
                proc = subprocess.run(
                    ["bash", "-n", str(script)], capture_output=True, text=True
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)


class InstallUninstallTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.appimage = self.home / "Preen-9.9.9-x86_64.AppImage"
        self.appimage.write_text(STUB_APPIMAGE)
        self.appimage.chmod(0o755)

    # --- install locations (user scope) ---

    def app_dir(self):
        return self.home / ".local" / "share" / "preen"

    def apps_dir(self):
        return self.home / ".local" / "share" / "applications"

    def icons_dir(self):
        return self.home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"

    def config_dir(self):
        return self.home / ".config" / "preen"

    def desktop_entry(self):
        return self.apps_dir() / DESKTOP_ID

    def install(self, *args, **kwargs):
        return run_script(INSTALLER, str(self.appimage), *args, home=self.home, **kwargs)

    def uninstall(self, *args, **kwargs):
        return run_script(UNINSTALLER, *args, home=self.home, **kwargs)

    def exec_line(self):
        for line in self.desktop_entry().read_text().splitlines():
            if line.startswith("Exec="):
                return line
        self.fail("no Exec= line in desktop entry")

    def test_installs_appimage_menu_entry_and_icon(self):
        proc = self.install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed = self.app_dir() / "Preen.AppImage"
        self.assertTrue(installed.exists())
        self.assertEqual(installed.read_text(), STUB_APPIMAGE)
        self.assertTrue(self.desktop_entry().exists())
        self.assertTrue((self.icons_dir() / "preen.png").exists())
        self.assertEqual(self.exec_line(), "Exec=%s" % installed)
        text = self.desktop_entry().read_text()
        self.assertIn("X-AppImage-Version=9.9.9", text)
        self.assertIn("StartupWMClass=preen", text)
        self.assertIn("Installed", proc.stdout)

    def test_reinstall_replaces_previous_install(self):
        self.assertEqual(self.install().returncode, 0)
        self.appimage.write_text(STUB_APPIMAGE + "# updated\n")
        proc = self.install()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed = self.app_dir() / "Preen.AppImage"
        self.assertEqual(installed.read_text(), STUB_APPIMAGE + "# updated\n")

    def test_quotes_exec_for_paths_with_spaces(self):
        spaced_home = self.home / "home with space"
        spaced_home.mkdir()
        proc = run_script(INSTALLER, str(self.appimage), home=spaced_home)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed = spaced_home / ".local" / "share" / "preen" / "Preen.AppImage"
        entry = spaced_home / ".local" / "share" / "applications" / DESKTOP_ID
        exec_line = next(
            line for line in entry.read_text().splitlines() if line.startswith("Exec=")
        )
        self.assertEqual(exec_line, 'Exec="%s"' % installed)

    def test_respects_xdg_data_home(self):
        xdg_data = self.home / "xdg-data"
        proc = self.install(extra_env={"XDG_DATA_HOME": str(xdg_data)})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((xdg_data / "preen" / "Preen.AppImage").exists())
        self.assertTrue((xdg_data / "applications" / DESKTOP_ID).exists())
        proc = run_script(
            UNINSTALLER, home=self.home, extra_env={"XDG_DATA_HOME": str(xdg_data)}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((xdg_data / "preen").exists())

    def test_uninstall_removes_everything(self):
        self.assertEqual(self.install().returncode, 0)
        proc = self.uninstall()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.app_dir().exists())
        self.assertFalse(self.desktop_entry().exists())
        self.assertFalse((self.icons_dir() / "preen.png").exists())
        self.assertIn("Removed", proc.stdout)
        again = self.uninstall()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("nothing to do", again.stdout)

    def test_purge_removes_settings(self):
        self.config_dir().mkdir(parents=True)
        (self.config_dir() / "settings.json").write_text("{}")
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.uninstall().returncode, 0)
        self.assertTrue(self.config_dir().exists())
        self.assertEqual(self.install().returncode, 0)
        proc = self.uninstall("--purge")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(self.config_dir().exists())

    @unittest.skipUnless(os.geteuid() != 0, "needs a non-root user")
    def test_system_scope_requires_root(self):
        proc = self.install("--system")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("root", proc.stderr)


if __name__ == "__main__":
    unittest.main()
