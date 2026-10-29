"""Tests for preen_tool.backend.appimages (AppImage scan/install/uninstall).

Uses a stub AppImage — a shell script that implements just enough of the
type-2 runtime (``--appimage-extract``) for the module's extraction steps —
plus a patched magic check, so no real AppImage, root, GTK or network is
needed. The magic check itself is tested separately on crafted bytes.
"""
import os
import stat
import tempfile
import unittest
from unittest import mock

from preen_tool.backend import appimages, utils

STUB_DESKTOP = """[Desktop Entry]
Type=Application
Name=Stub App
Comment=A stub application
Exec=stubapp
Icon=stubapp
X-AppImage-Version={version}
"""

STUB_APPIMAGE = """#!/usr/bin/env bash
# Stub AppImage: supports --appimage-extract the way the type-2 runtime does
# (writes matches under ./squashfs-root/).
set -euo pipefail
[ "${1:-}" = "--appimage-extract" ] || exit 1
pattern="$2"
mkdir -p squashfs-root
case "$pattern" in
    *.desktop)
        cat > squashfs-root/stubapp.desktop <<'EOF'
__DESKTOP_ENTRY__
EOF
        ;;
    *)
        printf 'png-bytes' > "squashfs-root/$pattern"
        ;;
esac
""".replace("__DESKTOP_ENTRY__", STUB_DESKTOP.format(version="1.2.3").strip())


class AppImagesTestBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self._old = {}
        for key in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
            self._old[key] = os.environ.get(key)
            if key == "HOME":
                os.environ[key] = self.home
            else:
                # Unset, never empty: xdg-utils merges associations correctly
                # only when the variables are absent or properly set.
                os.environ.pop(key, None)
        self.addCleanup(self._restore_env)
        self.downloads = os.path.join(self.home, "Downloads")
        os.makedirs(self.downloads)
        self.stub_path = os.path.join(self.downloads, "StubApp-1.2.3-x86_64.AppImage")
        with open(self.stub_path, "w", encoding="utf-8") as handle:
            handle.write(STUB_APPIMAGE)
        os.chmod(self.stub_path, 0o755)
        # The stub is a shell script, not an ELF; pretend it has the magic.
        patcher = mock.patch.object(appimages, "_is_type2_appimage", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _restore_env(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # --- locations ---

    def app_dir(self):
        return os.path.join(self.home, ".local", "share", "appimages")

    def entry_path(self, slug="stub-app"):
        return os.path.join(
            self.home, ".local", "share", "applications",
            "preen-appimage-{}.desktop".format(slug))

    def installed_image(self, slug="stub-app"):
        return os.path.join(self.app_dir(), slug + ".AppImage")

    def icon_path(self, slug="stub-app"):
        return os.path.join(
            self.home, ".local", "share", "icons", "hicolor", "256x256", "apps",
            slug + ".png")

    def _launcher_stub(self, marker):
        """A stub 'AppImage' that writes a marker file when executed."""
        path = os.path.join(self.downloads, "Launcher-1.0-x86_64.AppImage")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nprintf done > {}\n".format(marker))
        os.chmod(path, 0o755)
        return path


class MagicCheckTest(unittest.TestCase):
    def test_type2_magic_detected(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"\x7fELF" + b"JUNK" + b"AI\x02" + b"more-bytes")
            path = handle.name
        try:
            self.assertTrue(appimages._is_type2_appimage(path))
        finally:
            os.unlink(path)

    def test_plain_file_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".AppImage", delete=False) as handle:
            handle.write(b"#!/bin/sh\necho not an appimage\n")
            path = handle.name
        try:
            self.assertFalse(appimages._is_type2_appimage(path))
        finally:
            os.unlink(path)


class DownloadsDirTest(AppImagesTestBase):
    def test_falls_back_to_home_downloads(self):
        self.assertEqual(appimages.downloads_dir(), self.downloads)

    def test_parses_user_dirs_config(self):
        config = os.path.join(self.home, ".config")
        os.makedirs(config)
        with open(os.path.join(config, "user-dirs.dirs"), "w") as handle:
            handle.write('# commentary\nXDG_DOWNLOAD_DIR="$HOME/MyDownloads"\n')
        self.assertEqual(appimages.downloads_dir(),
                         os.path.join(self.home, "MyDownloads"))


class ListDownloadsTest(AppImagesTestBase):
    def test_lists_name_version_size_and_install_state(self):
        rows = appimages.list_downloads()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "download")
        self.assertEqual(row["path"], self.stub_path)
        self.assertEqual(row["name"], "Stub App")
        self.assertEqual(row["version"], "1.2.3")
        self.assertIn("MB", row["size"])
        self.assertFalse(row["installed"])

    def test_marks_installed_when_slugs_match(self):
        self.assertTrue(appimages.install_appimage(self.stub_path).ok)
        rows = appimages.list_downloads()
        self.assertTrue(rows[0]["installed"])


class InstallTest(AppImagesTestBase):
    def test_installs_appimage_entry_and_icon(self):
        outcome = appimages.install_appimage(self.stub_path)
        self.assertTrue(outcome.ok, outcome.message)
        image = self.installed_image()
        self.assertTrue(os.path.isfile(image))
        self.assertEqual(stat.S_IMODE(os.stat(image).st_mode) & 0o111, 0o111)
        entry = self.entry_path()
        self.assertTrue(os.path.isfile(entry))
        with open(entry, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Name=Stub App", content)
        self.assertIn("Exec={}".format(image), content)
        self.assertIn("X-AppImage-Version=1.2.3", content)
        self.assertIn("Icon=stub-app", content)
        self.assertTrue(os.path.isfile(self.icon_path()))
        # The download itself is never moved or deleted.
        self.assertTrue(os.path.isfile(self.stub_path))

    def test_reinstall_replaces_entry_and_image(self):
        self.assertTrue(appimages.install_appimage(self.stub_path).ok)
        with open(self.stub_path, "w", encoding="utf-8") as handle:
            handle.write(STUB_APPIMAGE.replace("1.2.3", "2.0.0"))
        outcome = appimages.install_appimage(self.stub_path)
        self.assertTrue(outcome.ok, outcome.message)
        with open(self.entry_path(), encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("X-AppImage-Version=2.0.0", content)
        self.assertEqual(len(appimages.list_installed()), 1)

    def test_missing_icon_degrades_to_generic_without_failing(self):
        # A .DirIcon symlink whose target is never extracted (real-world
        # Recordly case) must not fail the install — fall back to the
        # generic icon.
        phantom = """#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "--appimage-extract" ] || exit 1
pattern="$2"
mkdir -p squashfs-root
case "$pattern" in
    *.desktop)
        printf '[Desktop Entry]\\nType=Application\\nName=Phantom\\nExec=phantom\\nIcon=ghosticon\\n' > squashfs-root/stubapp.desktop
        ;;
    .DirIcon)
        ln -s ghosticon.png squashfs-root/.DirIcon
        ;;
    *)
        exit 0
        ;;
esac
"""
        path = os.path.join(self.downloads, "Phantom-1.0-x86_64.AppImage")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(phantom)
        os.chmod(path, 0o755)
        outcome = appimages.install_appimage(path)
        self.assertTrue(outcome.ok, outcome.message)
        with open(self.entry_path("phantom"), encoding="utf-8") as handle:
            self.assertIn("Icon=application-x-executable", handle.read())

    def test_icon_named_after_the_app_is_found_without_diricon_help(self):
        # Some AppImages ship <appname>.png at the root while the desktop
        # entry's Icon key matches nothing directly (the Recordly shape).
        renamed = STUB_APPIMAGE.replace("Icon=stubapp", "Icon=weird-key")
        path = os.path.join(self.downloads, "StubApp-2.0-x86_64.AppImage")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(renamed)
        os.chmod(path, 0o755)
        outcome = appimages.install_appimage(path)
        self.assertTrue(outcome.ok, outcome.message)
        # The stub only writes the icon pattern it is asked for, so the
        # root-level fallback asks for *.png and matches by app name.
        self.assertTrue(os.path.isfile(self.icon_path("stub-app")))

    def test_symlinked_icon_chain_is_resolved(self):
        # Real-world shape (Recordly): Icon=recordly, root recordly.png is a
        # symlink to usr/share/icons/... which is itself only reachable by
        # extraction, and .DirIcon points back at the root link.
        chained = """#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "--appimage-extract" ] || exit 1
pattern="$2"
mkdir -p squashfs-root
case "$pattern" in
    *.desktop)
        printf '[Desktop Entry]\\nType=Application\\nName=Chained\\nExec=chained\\nIcon=chained\\n' > squashfs-root/chained.desktop
        ;;
    .DirIcon)
        ln -s chained.png squashfs-root/.DirIcon
        ;;
    chained.png)
        ln -s usr/share/icons/hicolor/1024x1024/apps/chained.png squashfs-root/chained.png
        ;;
    usr/share/icons/hicolor/1024x1024/apps/chained.png)
        mkdir -p "squashfs-root/usr/share/icons/hicolor/1024x1024/apps"
        printf 'real-png' > squashfs-root/usr/share/icons/hicolor/1024x1024/apps/chained.png
        ;;
    *)
        exit 0
        ;;
esac
"""
        path = os.path.join(self.downloads, "Chained-1.0-x86_64.AppImage")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(chained)
        os.chmod(path, 0o755)
        outcome = appimages.install_appimage(path)
        self.assertTrue(outcome.ok, outcome.message)
        with open(self.entry_path("chained"), encoding="utf-8") as handle:
            self.assertIn("Icon=chained", handle.read())
        self.assertTrue(os.path.isfile(self.icon_path("chained")))

    def test_simulate_makes_no_changes(self):
        utils.set_simulate(True)
        try:
            outcome = appimages.install_appimage(self.stub_path)
        finally:
            utils.set_simulate(False)
        self.assertTrue(outcome.ok)
        self.assertFalse(os.path.exists(self.app_dir()))
        self.assertFalse(os.path.exists(self.entry_path()))

    def test_missing_file_fails(self):
        outcome = appimages.install_appimage(os.path.join(self.downloads, "nope.AppImage"))
        self.assertFalse(outcome.ok)


class ListInstalledTest(AppImagesTestBase):
    def test_sees_our_install_as_managed(self):
        self.assertTrue(appimages.install_appimage(self.stub_path).ok)
        rows = appimages.list_installed()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "installed")
        self.assertEqual(row["name"], "Stub App")
        self.assertEqual(row["version"], "1.2.3")
        self.assertTrue(row["managed"])
        self.assertEqual(row["path"], self.installed_image())


class UninstallTest(AppImagesTestBase):
    def test_removes_entry_icon_and_managed_binary(self):
        self.assertTrue(appimages.install_appimage(self.stub_path).ok)
        outcome = appimages.uninstall_appimage("preen-appimage-stub-app.desktop")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertFalse(os.path.exists(self.installed_image()))
        self.assertFalse(os.path.exists(self.entry_path()))
        self.assertFalse(os.path.exists(self.icon_path()))
        # The download in ~/Downloads is untouched.
        self.assertTrue(os.path.isfile(self.stub_path))

    def test_keeps_binary_outside_the_managed_dir(self):
        foreign = os.path.join(self.downloads, "Foreign-3.0-x86_64.AppImage")
        with open(foreign, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        os.chmod(foreign, 0o755)
        entry = os.path.join(self.home, ".local", "share", "applications",
                             "preen-appimage-foreign.desktop")
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        with open(entry, "w", encoding="utf-8") as handle:
            handle.write("[Desktop Entry]\nType=Application\nName=Foreign\n"
                         "Exec={}\nIcon=foreign\n".format(foreign))
        outcome = appimages.uninstall_appimage("preen-appimage-foreign.desktop")
        self.assertTrue(outcome.ok, outcome.message)
        self.assertFalse(os.path.exists(entry))
        self.assertTrue(os.path.isfile(foreign), "foreign binary must survive")

    def test_rejects_bad_ids(self):
        self.assertFalse(appimages.uninstall_appimage("../evil").ok)
        self.assertFalse(appimages.uninstall_appimage("missing.desktop").ok)


class InstallDebTest(AppImagesTestBase):
    def test_rejects_non_deb(self):
        outcome = appimages.install_deb(self.stub_path)
        self.assertFalse(outcome.ok)

    def test_simulate_reports_without_running(self):
        utils.set_simulate(True)
        try:
            outcome = appimages.install_deb(self.stub_path.replace(
                ".AppImage", ".deb"))
        finally:
            utils.set_simulate(False)
        # The .deb does not exist, so the upfront file check fails first —
        # create it and expect the simulated outcome.
        self.assertFalse(outcome.ok)
        deb = os.path.join(self.downloads, "stub.deb")
        with open(deb, "w") as handle:
            handle.write("stub")
        utils.set_simulate(True)
        try:
            outcome = appimages.install_deb(deb)
        finally:
            utils.set_simulate(False)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.message, "Simulation complete. No changes were made.")


class RightClickIntegrationTest(AppImagesTestBase):
    """run_appimage, name lookup, and the file-manager integration helpers."""

    def test_run_appimage_launches_detached(self):
        marker = os.path.join(self.downloads, "launched.marker")
        path = self._launcher_stub(marker)
        outcome = appimages.run_appimage(path)
        self.assertTrue(outcome.ok, outcome.message)
        for _ in range(40):  # the launch is asynchronous
            if os.path.isfile(marker):
                break
            import time
            time.sleep(0.05)
        self.assertTrue(os.path.isfile(marker), "stub AppImage never ran")

    def test_run_appimage_rejects_missing_files(self):
        self.assertFalse(appimages.run_appimage(
            os.path.join(self.downloads, "nope.AppImage")).ok)

    def test_app_name_prefers_the_embedded_entry(self):
        self.assertEqual(appimages.app_name_for_file(self.stub_path), "Stub App")
        plain = os.path.join(self.downloads, "Plain-2.0.AppImage")
        with open(plain, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        # The base class pretends every file has the type-2 magic, so restore
        # the real check for this one and expect the filename stem.
        with mock.patch.object(appimages, "_is_type2_appimage", return_value=False):
            self.assertEqual(appimages.app_name_for_file(plain), "Plain-2.0")

    def test_find_installed_for_file_matches_by_slug(self):
        self.assertIsNone(appimages.find_installed_for_file(self.stub_path))
        self.assertTrue(appimages.install_appimage(self.stub_path).ok)
        row = appimages.find_installed_for_file(self.stub_path)
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Stub App")
        self.assertTrue(row["managed"])

    def test_filemanager_scripts_roundtrip(self):
        self.assertFalse(appimages.filemanager_scripts_installed())
        outcome = appimages.set_filemanager_scripts(True)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue(appimages.filemanager_scripts_installed())
        scripts_dir = appimages.nautilus_scripts_dir()
        install_script = os.path.join(scripts_dir, appimages.FM_SCRIPT_INSTALL)
        self.assertEqual(stat.S_IMODE(os.stat(install_script).st_mode) & 0o111, 0o111)
        with open(install_script, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("--appimage-handler", content)
        self.assertIn("preen", content)
        with open(os.path.join(scripts_dir, appimages.FM_SCRIPT_RUN),
                  encoding="utf-8") as handle:
            self.assertIn("--appimage-run", handle.read())
        outcome = appimages.set_filemanager_scripts(False)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertFalse(appimages.filemanager_scripts_installed())

    def test_filemanager_scripts_simulate_makes_nothing(self):
        utils.set_simulate(True)
        try:
            outcome = appimages.set_filemanager_scripts(True)
        finally:
            utils.set_simulate(False)
        self.assertTrue(outcome.ok)
        self.assertFalse(appimages.filemanager_scripts_installed())

    def test_default_appimage_handler_roundtrip(self):
        # xdg-mime honours XDG_CONFIG_HOME/XDG_DATA_HOME, which the base class
        # points at a temp dir, so the default never leaks into the real
        # configuration. The query only reports a handler whose desktop file
        # exists, so install the shipped handler entry into the sandbox too.
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        apps_dir = os.path.join(
            os.environ.get("XDG_DATA_HOME") or
            os.path.join(self.home, ".local", "share"), "applications")
        os.makedirs(apps_dir, exist_ok=True)
        with open(os.path.join(repo, "data", "io.github.mdadeel.Preen.appimage.desktop"),
                  encoding="utf-8") as handle:
            body = handle.read()
        with open(os.path.join(apps_dir, appimages.HANDLER_ENTRY_ID),
                  "w", encoding="utf-8") as handle:
            handle.write(body)
        outcome = appimages.set_default_appimage_handler()
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(appimages.default_appimage_handler(),
                         appimages.HANDLER_ENTRY_ID)
        # The association is written as a real [Default Applications] entry.
        config_dir = os.environ.get("XDG_CONFIG_HOME") or \
            os.path.join(self.home, ".config")
        with open(os.path.join(config_dir, "mimeapps.list"), encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[Default Applications]", content)
        self.assertIn("application/vnd.appimage=" + appimages.HANDLER_ENTRY_ID,
                      content)


class HandlerCLITest(AppImagesTestBase):
    """The --appimage-run entry point (GTK-free) and its argument handling."""

    def test_appimage_run_flag_launches_and_exits_zero(self):
        from preen_tool import app
        marker = os.path.join(self.downloads, "cli-launched.marker")
        path = self._launcher_stub(marker)
        code = app.main(["--appimage-run", path])
        self.assertEqual(code, 0)
        for _ in range(40):
            if os.path.isfile(marker):
                break
            import time
            time.sleep(0.05)
        self.assertTrue(os.path.isfile(marker))

    def test_handler_flags_need_a_file(self):
        from preen_tool import app
        self.assertEqual(app.main(["--appimage-handler"]), 2)
        self.assertEqual(app.main(["--deb-handler"]), 2)
        self.assertEqual(app.main(["--appimage-run"]), 2)


if __name__ == "__main__":
    unittest.main()
