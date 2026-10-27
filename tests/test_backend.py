"""Regression tests for every bug found in the roast.

Run with:  python3 -m unittest discover -s tests -v
      or:  pytest -q
"""
from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from preen_tool import app, cli  # noqa: E402
from preen_tool.backend import (  # noqa: E402
    apps,
    backup,
    dashboard,
    performance,
    system,
    ui_customization,
    utils,
)
from tests.fakes import FakeSystem  # noqa: E402


class ListLog:
    def __init__(self):
        self.lines = []

    def append(self, text):
        self.lines.append(str(text))

    def text(self):
        return "".join(self.lines)


class BackendTestCase(unittest.TestCase):
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

        self.user_autostart = self.root / "autostart-user"
        self.sys_autostart = self.root / "autostart-system"
        self.user_autostart.mkdir()
        self.sys_autostart.mkdir()
        self.css_dir = self.root / "gtk-3.0"
        self.config_dir = self.fake.config_dir
        self.swapfile = self.root / "swapfile"
        self.zram_cfg = self.root / "zram-generator.conf"

        patches = [
            mock.patch.object(system, "AUTOSTART_DIRS",
                              [str(self.user_autostart), str(self.sys_autostart)]),
            mock.patch.object(ui_customization, "CSS_DIR", str(self.css_dir)),
            mock.patch.object(ui_customization, "CSS_PATH", str(self.css_dir / "gtk.css")),
            mock.patch.object(backup, "CONFIG_DIR", str(self.config_dir)),
            mock.patch.object(performance, "SWAPFILE", str(self.swapfile)),
            mock.patch.object(performance, "FSTAB_ENTRY",
                              str(self.swapfile) + " none swap sw 0 0"),
            mock.patch.object(performance, "ZRAM_CFG", str(self.zram_cfg)),
            mock.patch.object(performance, "_has_zram_generator", return_value=True),
            mock.patch.object(ui_customization, "_installed_themes",
                              return_value={"Adwaita", "Adwaita-dark"}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        apps.invalidate_state()
        self.addCleanup(apps.invalidate_state)
        self.log = ListLog()

    # ------------------------------------------------------------------
    # Catalogue / packaging
    # ------------------------------------------------------------------
    def test_catalog_and_presets_are_valid(self):
        self.assertEqual(apps.validate_catalog(), [])
        self.assertGreaterEqual(len(apps.all_apps()), 40)
        refs = [ref for item in apps.all_apps().values() for ref in apps.as_list(item.get("flatpak"))]
        # Runtime/SDK extensions are not installable applications.
        self.assertFalse(any(".Sdk.Extension." in ref or ".VulkanLayer." in ref for ref in refs))
        for name, ids in apps.load_presets().items():
            self.assertTrue(ids, "preset {} is empty".format(name))
            for app_id in ids:
                self.assertIn(app_id, apps.all_apps())

    def test_built_wheel_contains_the_backend(self):
        """The original .deb/wheel shipped without backend/ - app crashed on start."""
        try:
            import wheel  # noqa: F401
            import setuptools.build_meta as build_meta
        except ImportError:
            self.skipTest("setuptools/wheel build backend not installed")

        out = tempfile.mkdtemp()
        self.addCleanup(lambda: [p.unlink() for p in Path(out).glob("*")])
        wheel_name = build_meta.build_wheel(out)
        with zipfile.ZipFile(Path(out) / wheel_name) as archive:
            names = set(archive.namelist())
        for required in (
            "preen_tool/app.py",
            "preen_tool/gui.py",
            "preen_tool/cli.py",
            "preen_tool/backend/apps.py",
            "preen_tool/backend/utils.py",
            "preen_tool/backend/settings.py",
            "preen_tool/backend/performance.py",
            "preen_tool/backend/backup.py",
            "preen_tool/backend/ui_customization.py",
            "preen_tool/config/apps.json",
            "preen_tool/config/presets.json",
        ):
            self.assertIn(required, names, "wheel is missing " + required)

    # ------------------------------------------------------------------
    # Command runner
    # ------------------------------------------------------------------
    def test_run_cmd_merges_env_instead_of_replacing_it(self):
        result = utils.run_cmd([
            sys.executable, "-c",
            "import os; print(os.environ.get('ZOPT_TEST_VAR','missing')); "
            "print(bool(os.environ.get('PATH')))",
        ], env={"ZOPT_TEST_VAR": "yes"}, mutate=False)
        self.assertTrue(result.ok)
        self.assertIn("yes", result.out)
        self.assertIn("True", result.out)

    def test_run_cmd_reports_failures(self):
        report = utils.Report(self.log)
        result = report.run(["failcmd"], mutate=False)
        self.assertEqual(result.code, 3)
        outcome = report.finish("all good", "it broke")
        self.assertFalse(outcome.ok)
        self.assertIn("boom", " ".join(outcome.details))

    def test_pkexec_is_added_once_and_stripped_for_root(self):
        utils.run_cmd(["bash", "-c", "echo hi"], use_pkexec=True, mutate=True)
        self.assertEqual(self.fake.commands()[-1]["cmd"], "pkexec")
        self.fake.clear_log()
        with mock.patch("preen_tool.backend.utils.os.geteuid", return_value=0):
            utils.run_cmd(["bash", "-c", "echo hi"], use_pkexec=True, mutate=True)
        self.assertEqual(self.fake.commands()[-1]["cmd"], "bash")

    def test_run_actions_never_reexecutes_on_internal_typeerror(self):
        counter = []

        def broken(log=None):
            counter.append(1)
            raise TypeError("internal bug")

        outcome = utils.run_actions([("broken step", broken, ())], log=self.log)
        self.assertFalse(outcome.ok)
        self.assertEqual(len(counter), 1, "a TypeError must not cause a second execution")

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def test_purged_package_is_not_reported_as_installed(self):
        self.fake.update(apt={
            "ghostpkg": "purge ok not-installed",
            "realpkg": "install ok installed",
        })
        apps.invalidate_state()
        self.assertFalse(apps._apt_installed("ghostpkg"))
        self.assertTrue(apps._apt_installed("realpkg"))

    def test_status_detection_uses_two_queries_not_forty(self):
        self.fake.update(flatpaks=["org.videolan.VLC"],
                         apt={"vlc": "install ok installed"})
        apps.invalidate_state()
        self.fake.clear_log()
        status = apps.get_status_label_map()
        self.assertEqual(status["vlc"], "Installed (Flatpak, APT)")
        commands = self.fake.commands()
        self.assertEqual(sum(1 for c in commands if c["cmd"] == "flatpak"), 1)
        self.assertEqual(sum(1 for c in commands if c["cmd"] == "dpkg-query"), 1)
        self.assertLessEqual(len(commands), 2)

    # ------------------------------------------------------------------
    # Install / update / uninstall
    # ------------------------------------------------------------------
    def test_install_batches_apt_into_one_polkit_prompt(self):
        outcome = apps.install_apps(["vlc", "git"], "apt", log=self.log)
        self.assertTrue(outcome.ok, "".join(outcome.details))
        pkexec_calls = [c for c in self.fake.commands() if c["cmd"] == "pkexec"]
        self.assertEqual(len(pkexec_calls), 1)
        script = pkexec_calls[0]["args"][-1]
        self.assertIn("apt-get install -y vlc git", script)
        self.assertIn("apt-get update", script)
        self.assertNotIn("flatpak install", script)

    def test_flatpak_install_uses_one_command_and_flathub(self):
        outcome = apps.install_apps(["spotify", "discord"], "flatpak", log=self.log)
        self.assertTrue(outcome.ok)
        flatpak_installs = [c for c in self.fake.commands()
                            if c["cmd"] == "flatpak" and c["args"][0] == "install"]
        self.assertEqual(len(flatpak_installs), 1)
        self.assertIn("flathub", flatpak_installs[0]["args"])
        self.assertIn("com.spotify.Client", flatpak_installs[0]["args"])

    def test_missing_source_falls_back_to_the_other_package_manager(self):
        outcome = apps.install_apps(["git"], "flatpak", log=self.log)
        self.assertTrue(outcome.ok)
        self.assertIn("no flatpak package", self.log.text())
        scripts = [c["args"][-1] for c in self.fake.commands() if c["cmd"] == "pkexec"]
        self.assertTrue(any("apt-get install -y git" in script for script in scripts))

    def test_scanner_entries_are_validated_and_essentials_protected(self):
        outcome = apps.uninstall_installed([
            {"source": "apt", "id": "foo; touch /tmp/pwned"},
            {"source": "flatpak", "id": "../evil"},
            {"source": "apt", "id": "gnome-shell"},
        ], log=self.log)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.fake.mutating_commands(), [])
        self.assertIn("invalid entry", self.log.text())

    def test_bulk_operations_are_batched(self):
        apps.update_installed([
            {"source": "flatpak", "id": "com.spotify.Client"},
            {"source": "flatpak", "id": "com.discordapp.Discord"},
            {"source": "apt", "id": "vlc"},
        ], log=self.log)
        flatpak_updates = [c for c in self.fake.commands()
                           if c["cmd"] == "flatpak" and c["args"][0] == "update"]
        self.assertEqual(len(flatpak_updates), 1)
        self.assertEqual(len(flatpak_updates[0]["args"]), 5)

    # ------------------------------------------------------------------
    # Simulate mode - the big one
    # ------------------------------------------------------------------
    def test_simulate_mode_blocks_EVERY_mutating_action(self):
        self.swapfile.write_bytes(b"x")  # disable_swapfile would otherwise delete it
        self.fake.update(swap=[str(self.swapfile)], flatpaks=[], apt={"vlc": "install ok installed"})
        apps.invalidate_state()

        desktop = self.sys_autostart / "demo.desktop"
        desktop.write_text("[Desktop Entry]\nType=Application\nName=Demo\nExec=demo\n",
                           encoding="utf-8")
        desktop_before = desktop.read_text(encoding="utf-8")
        (self.config_dir / "settings.ini").write_text("a=1\n", encoding="utf-8")
        dummy_tar = self.root / "dummy.tar"
        dummy_tar.write_bytes(b"not a tar, but simulate returns before reading it")
        css_path = self.css_dir / "gtk.css"

        utils.set_simulate(True)
        self.fake.clear_log()

        calls = [
            lambda: apps.install_apps(["vlc", "spotify"], "flatpak", log=self.log),
            lambda: apps.update_all("apt", log=self.log),
            lambda: apps.uninstall_apps(["vlc"], "apt", log=self.log),
            lambda: apps.uninstall_installed([{"source": "apt", "id": "vlc"}], log=self.log),
            lambda: system.run_cleanup(log=self.log),
            lambda: system.set_animations(False, log=self.log),
            lambda: system.set_startup_app(str(desktop), False, log=self.log),
            lambda: performance.set_power_profile("performance", log=self.log),
            lambda: performance.enable_swapfile(2, log=self.log),
            lambda: performance.disable_swapfile(log=self.log),
            lambda: performance.enable_zram(log=self.log),
            lambda: performance.disable_zram(log=self.log),
            lambda: ui_customization.apply_theme_mode("dark", log=self.log),
            lambda: ui_customization.install_icon_pack(str(dummy_tar), log=self.log),
            lambda: ui_customization.set_rounded_corners(True, log=self.log),
            lambda: backup.export_configs(str(self.root / "export.tar.xz"), log=self.log),
            lambda: backup.import_configs(str(dummy_tar), log=self.log),
            lambda: backup.timeshift_snapshot(log=self.log),
            lambda: backup.open_timeshift_gui(log=self.log),
        ]
        for call in calls:
            call()

        self.assertEqual(self.fake.mutating_commands(), [],
                         "Simulate mode spawned a real mutating command")
        self.assertFalse((self.root / "export.tar.xz").exists())
        self.assertFalse(css_path.exists())
        self.assertTrue(self.swapfile.exists())
        self.assertEqual(desktop.read_text(encoding="utf-8"), desktop_before)
        self.assertFalse((self.user_autostart / "demo.desktop").exists())
        self.assertIn("[simulate]", self.log.text())

    # ------------------------------------------------------------------
    # Optimize / performance
    # ------------------------------------------------------------------
    def test_disable_swapfile_is_a_noop_when_no_swapfile_exists(self):
        self.fake.update(swap=[])
        outcome = performance.disable_swapfile(log=self.log)
        self.assertTrue(outcome.ok)
        self.assertEqual(self.fake.mutating_commands(), [],
                         "must not spawn pkexec/sed/rm when nothing to disable")

    def test_power_profile_is_validated(self):
        self.assertFalse(performance.set_power_profile("; rm -rf /", log=self.log).ok)
        self.assertEqual(self.fake.mutating_commands(), [])
        self.assertTrue(performance.set_power_profile("performance", log=self.log).ok)

    def test_startup_entries_are_merged_and_toggled_safely(self):
        system_entry = self.sys_autostart / "demo.desktop"
        system_entry.write_text(
            "[Desktop Entry]\nType=Application\nName=Demo\nExec=demo\n"
            "[Extra Group]\nKeep=me\n", encoding="utf-8")
        items = system.list_startup_apps()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Demo")

        outcome = system.set_startup_app(str(system_entry), False, log=self.log)
        self.assertTrue(outcome.ok)
        override = self.user_autostart / "demo.desktop"
        content = override.read_text(encoding="utf-8")
        self.assertIn("Hidden=true", content)
        self.assertIn("X-GNOME-Autostart-enabled=false", content)
        self.assertIn("[Extra Group]", content)
        self.assertIn("Keep=me", content)
        self.assertTrue(system.list_startup_apps()[0]["hidden"])

        self.assertTrue(system.set_startup_app(str(override), True, log=self.log).ok)
        self.assertFalse(system.list_startup_apps()[0]["hidden"])

    # ------------------------------------------------------------------
    # Tar safety
    # ------------------------------------------------------------------
    def _make_archive(self, path, members):
        with tarfile.open(path, "w") as tar:
            for name, kind, data in members:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    tar.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = data
                    tar.addfile(info)
                else:
                    payload = data.encode() if isinstance(data, str) else data
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))

    def test_desktop_keys_survive_a_file_without_trailing_newline(self):
        path = self.root / "truncated.desktop"
        path.write_text("[Desktop Entry]\nType=Application\nName=T\nExec=app",
                        encoding="utf-8")  # deliberately no final newline
        self.assertTrue(utils.set_autostart_hidden(str(path), True))
        content = path.read_text(encoding="utf-8")
        self.assertIn("Exec=app\n", content)
        self.assertIn("Hidden=true\n", content)
        self.assertIn("X-GNOME-Autostart-enabled=false\n", content)
        self.assertTrue(utils.read_desktop_entry(str(path))[1])

    def test_config_export_import_roundtrip_with_symlinks_present(self):
        """An exported archive must always be restorable by this same tool."""
        (self.config_dir / "settings.ini").write_text("original\n", encoding="utf-8")
        try:
            (self.config_dir / "link").symlink_to("settings.ini")
        except OSError:
            self.skipTest("symlinks unsupported on this filesystem")
        archive = self.root / "backup.tar.xz"
        self.assertTrue(backup.export_configs(str(archive), log=self.log).ok)
        (self.config_dir / "settings.ini").write_text("changed\n", encoding="utf-8")
        self.assertTrue(backup.import_configs(str(archive), log=self.log).ok)
        self.assertEqual((self.config_dir / "settings.ini").read_text(encoding="utf-8"), "original\n")

    def test_config_export_import_roundtrip(self):
        (self.config_dir / "settings.ini").write_text("original\n", encoding="utf-8")
        archive = self.root / "backup.tar.xz"
        self.assertTrue(backup.export_configs(str(archive), log=self.log).ok)
        self.assertTrue(archive.exists())
        (self.config_dir / "settings.ini").write_text("changed\n", encoding="utf-8")
        self.assertTrue(backup.import_configs(str(archive), log=self.log).ok)
        self.assertEqual((self.config_dir / "settings.ini").read_text(encoding="utf-8"), "original\n")

    def test_config_import_refuses_traversal_links_and_absolute_paths(self):
        malicious = self.root / "evil.tar"
        self._make_archive(malicious, [
            (".config/good.txt", "file", "safe"),
            ("../escaped.txt", "file", "pwned"),
            ("/tmp/absolute.txt", "file", "pwned"),
            (".config/link", "symlink", "/etc/passwd"),
            (".config/../../home/escape2.txt", "file", "pwned"),
        ])
        outcome = backup.import_configs(str(malicious), log=self.log)
        self.assertFalse(outcome.ok)
        self.assertFalse((self.fake.home / "escaped.txt").exists())
        self.assertFalse((self.fake.home / "escape2.txt").exists())
        self.assertFalse((self.config_dir / "good.txt").exists())

    def test_icon_pack_refuses_traversal_and_installs_a_real_theme(self):
        evil = self.root / "evil-icons.tar.xz"
        self._make_archive(evil, [("../escaped-icons.txt", "file", "pwned")])
        self.assertFalse(ui_customization.install_icon_pack(str(evil), log=self.log).ok)
        self.assertFalse((self.fake.home / "escaped-icons.txt").exists())

        good = self.root / "icons.tar.xz"
        self._make_archive(good, [
            ("MyIcons", "dir", None),
            ("MyIcons/index.theme", "file", "[Icon Theme]\nName=MyIcons\n"),
            ("MyIcons/icon.png", "file", b"\x00"),
        ])
        outcome = ui_customization.install_icon_pack(str(good), log=self.log)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue((self.fake.icons_dir / "MyIcons" / "index.theme").exists())
        set_calls = [c for c in self.fake.commands()
                     if c["cmd"] == "gsettings" and c["args"][0] == "set"]
        self.assertTrue(any("MyIcons" in c["args"] for c in set_calls))

    def test_rounded_corners_css_is_idempotent_and_removable(self):
        self.assertTrue(ui_customization.set_rounded_corners(True, log=self.log).ok)
        self.assertTrue(ui_customization.set_rounded_corners(True, log=self.log).ok)
        css = (self.css_dir / "gtk.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS"), 1)
        self.assertTrue(ui_customization.set_rounded_corners(False, log=self.log).ok)
        self.assertNotIn("BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS",
                         (self.css_dir / "gtk.css").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # CLI / doctor
    # ------------------------------------------------------------------
    def test_cli_commands_work_without_gtk(self):
        import contextlib

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--check-catalog"]), 0)
            self.assertEqual(cli.main(["--version"]), 0)
            self.assertEqual(app.main(["--doctor"]), 0)
        report = cli.collect_report()
        self.assertEqual(report["problems"], [])
        self.assertGreater(report["catalog_entries"], 40)
        self.assertTrue(any(row["name"] == "Installed package layout"
                            and row["status"] == "ok" for row in report["capabilities"]))

    def test_feature_warnings_explain_missing_tools_in_plain_language(self):
        with mock.patch.object(dashboard, "has_command", return_value=False):
            warnings = dashboard.feature_warnings()
        self.assertTrue(any("Flatpak" in w for w in warnings))
        self.assertTrue(any("polkit" in w for w in warnings))
        self.assertTrue(any("Timeshift" in w for w in warnings))

    def test_dashboard_works_without_psutil(self):
        with mock.patch.object(dashboard, "psutil", None):
            info = dashboard.get_system_info()
        for key in ("cpu_percent", "mem_percent", "disk_percent", "os", "kernel", "uptime"):
            self.assertIn(key, info)


if __name__ == "__main__":
    unittest.main(verbosity=2)
