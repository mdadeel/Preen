"""Backend regression tests.

Run with:  python3 -m unittest discover -s tests -v
      or:  pytest -q
"""
from __future__ import annotations

import io
import os
import subprocess
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
    drivers,
    maintenance,
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
            metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
            # setuptools >= 77 moves the licence under dist-info/licenses/.
            license_name = next(name for name in names
                                if name.endswith(".dist-info/LICENSE")
                                or name.endswith(".dist-info/licenses/LICENSE"))
            metadata = archive.read(metadata_name).decode("utf-8")
            self.assertEqual(archive.read(license_name), (REPO / "LICENSE").read_bytes())
        self.assertIn("Project-URL: Privacy, https://github.com/mdadeel/Preen/blob/main/PRIVACY.md", metadata)
        self.assertIn("Project-URL: Security, https://github.com/mdadeel/Preen/blob/main/SECURITY.md", metadata)
        self.assertIn("License :: OSI Approved :: MIT License", metadata)
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
            "preen_tool/assets/preen.png",
            "preen_tool/assets/preen.svg",
            "preen_tool/assets/controls/check.png",
            "preen_tool/assets/controls/mixed.png",
            "preen_tool/assets/controls/radio.png",
            "preen_tool/assets/brand/firefox.png",
            "preen_tool/assets/brand/LICENSE.simple-icons.md",
        ):
            self.assertIn(required, names, "wheel is missing " + required)

    def test_catalogue_rejects_unsafe_or_missing_icon_assets(self):
        entry = {"id": "demo", "name": "Demo", "apt": "demo", "icon_asset": "../outside"}
        with mock.patch.object(apps, "load_apps", return_value={"Demo": [entry]}), \
                mock.patch.object(apps, "load_presets", return_value={}):
            self.assertTrue(any("invalid icon asset" in p for p in apps.validate_catalog()))
            entry["icon_asset"] = "nonexistent"
            self.assertTrue(any("missing icon asset" in p for p in apps.validate_catalog()))

    def test_apt_scanner_keeps_desktop_entry_icon(self):
        launcher = self.root / "demo.desktop"
        launcher.write_text("[Desktop Entry]\nType=Application\nName=Demo\n"
                            "Icon=demo-icon\n[Other Group]\nIcon=wrong\n", encoding="utf-8")
        self.fake.update(owners={str(launcher): "demo"})
        with mock.patch.object(apps.glob, "glob", return_value=[str(launcher)]):
            entries = apps.list_installed_apt()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["icon"], "demo-icon")

    def test_desktop_search_dirs_skip_snapd_and_dedupe(self):
        with mock.patch.dict(os.environ, {
            "XDG_DATA_DIRS": "/var/lib/snapd/desktop:/usr/share:/usr/local/share:/usr/share",
        }):
            dirs = apps._desktop_search_dirs()
        self.assertNotIn("/var/lib/snapd/desktop", dirs)
        self.assertEqual(dirs[0], os.path.join(os.path.expanduser("~"), ".local", "share"))
        self.assertIn("/usr/share", dirs)
        self.assertEqual(len(dirs), len(set(dirs)))

    def test_apt_scanner_scans_xdg_dirs_and_prefers_user_launcher(self):
        sys_dir = self.root / "sysdata" / "applications"
        user_dir = self.fake.home / ".local" / "share" / "applications"
        sys_dir.mkdir(parents=True)
        user_dir.mkdir(parents=True)
        sys_launcher = sys_dir / "demo.desktop"
        sys_launcher.write_text("[Desktop Entry]\nType=Application\nName=Demo\n", encoding="utf-8")
        user_launcher = user_dir / "demo.desktop"
        user_launcher.write_text("[Desktop Entry]\nType=Application\nName=My Demo\n", encoding="utf-8")
        self.fake.update(owners={str(sys_launcher): "demo", str(user_launcher): "demo"})
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": str(sys_dir.parent)}):
            entries = apps.list_installed_apt()
        self.assertEqual([entry["name"] for entry in entries], ["My Demo"])
        self.assertEqual(entries[0]["desktop"], "demo.desktop")
        self.assertEqual(entries[0]["id"], "demo")

    def test_apt_scanner_lists_each_launcher_of_a_package(self):
        apps_dir = self.root / "data" / "applications"
        apps_dir.mkdir(parents=True)
        main = apps_dir / "suite-main.desktop"
        main.write_text("[Desktop Entry]\nType=Application\nName=Suite\n", encoding="utf-8")
        editor = apps_dir / "suite-editor.desktop"
        editor.write_text("[Desktop Entry]\nType=Application\nName=Suite Editor\n", encoding="utf-8")
        dup = apps_dir / "suite-copy.desktop"
        dup.write_text("[Desktop Entry]\nType=Application\nName=Suite\n", encoding="utf-8")
        hidden = apps_dir / "suite-hidden.desktop"
        hidden.write_text("[Desktop Entry]\nType=Application\nName=Suite Hidden\nNoDisplay=true\n",
                          encoding="utf-8")
        self.fake.update(owners={str(path): "suite" for path in (main, editor, dup, hidden)})
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": str(apps_dir.parent)}):
            entries = apps.list_installed_apt()
        self.assertEqual(sorted(entry["name"] for entry in entries), ["Suite", "Suite Editor"])
        self.assertEqual({entry["id"] for entry in entries}, {"suite"})

    def test_apt_scanner_recovers_when_batch_ownership_query_fails(self):
        apps_dir = self.root / "data" / "applications"
        apps_dir.mkdir(parents=True)
        good = apps_dir / "good.desktop"
        good.write_text("[Desktop Entry]\nType=Application\nName=Good\n", encoding="utf-8")
        other = apps_dir / "other.desktop"
        other.write_text("[Desktop Entry]\nType=Application\nName=Other\n", encoding="utf-8")
        self.fake.update(owners={str(good): "goodpkg"}, dpkg_S_batch_fail=True)
        warnings: list = []
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": str(apps_dir.parent)}):
            entries = apps.list_installed_apt(warnings=warnings, log=self.log)
        self.assertEqual([entry["name"] for entry in entries], ["Good"])
        self.assertTrue(any("exit 2" in warning for warning in warnings))

    def test_parse_desktop_file_prefers_name_for_current_locale(self):
        path = self.root / "loc.desktop"
        path.write_text("[Desktop Entry]\nType=Application\nName=Backup\n"
                        "Name[nl]=Reservekopie\nName[nl_BE]=Reservekopie (BE)\n",
                        encoding="utf-8")
        with mock.patch.dict(os.environ, {"LC_ALL": "nl_BE.UTF-8", "LANG": "en_US.UTF-8"}):
            self.assertEqual(utils.parse_desktop_file(str(path))["name"], "Reservekopie (BE)")
        with mock.patch.dict(os.environ, {"LC_ALL": "nl_NL.UTF-8"}):
            self.assertEqual(utils.parse_desktop_file(str(path))["name"], "Reservekopie")
        with mock.patch.dict(os.environ, {"LC_ALL": "C", "LANG": "C"}):
            self.assertEqual(utils.parse_desktop_file(str(path))["name"], "Backup")
        with mock.patch.dict(os.environ, {"LC_ALL": "fr_FR.UTF-8", "LANG": "fr_FR.UTF-8"}):
            self.assertEqual(utils.parse_desktop_file(str(path))["name"], "Backup")

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

    def test_simulated_privileged_commands_need_no_polkit_and_report_preview(self):
        utils.set_simulate(True)
        with mock.patch.object(utils.os, "geteuid", return_value=1000), \
                mock.patch.object(utils, "has_command", return_value=False), \
                mock.patch.object(utils.subprocess, "Popen") as popen:
            report = utils.Report(self.log)
            result = report.run(["journalctl", "--vacuum-size=100M"],
                                use_pkexec=True, mutate=True)
            self.assertTrue(result.simulated)
            self.assertIn("pkexec journalctl", result.out)
            self.assertIn("Simulation complete", report.finish("Done").message)
            outcome = utils.run_actions([("dry step", lambda: utils.ok("Done"), ())])
            self.assertIn("No changes were made", outcome.message)
            popen.assert_not_called()
        self.assertIn("[simulate] would run", self.log.text())

    def test_command_log_preserves_complete_stdout_stderr_and_exit_code(self):
        stdout = "out-start-" + "o" * 1600 + "-out-end"
        stderr = "err-start-" + "e" * 1600 + "-err-end"
        result = utils.run_cmd([sys.executable, "-c",
                                "import sys; sys.stdout.write({!r}); "
                                "sys.stderr.write({!r}); sys.exit(9)".format(stdout, stderr)],
                               log=self.log)
        self.assertEqual(result.code, 9)
        text = self.log.text()
        self.assertIn("[failed] exit 9", text)
        self.assertIn(stdout, text)
        self.assertIn(stderr, text)

    def test_run_actions_never_reexecutes_on_internal_typeerror(self):
        counter = []

        def broken(log=None):
            counter.append(1)
            raise TypeError("internal bug")

        outcome = utils.run_actions([("broken step", broken, ())], log=self.log)
        self.assertFalse(outcome.ok)
        self.assertEqual(len(counter), 1, "a TypeError must not cause a second execution")
        self.assertIn("Traceback", self.log.text())
        self.assertIn("internal bug", self.log.text())

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

    def test_failed_package_scan_is_unknown_and_blocks_relevant_actions(self):
        warning = "flatpak list failed: database unavailable"
        with mock.patch.object(apps, "get_installed_state", return_value=(set(), set(), [warning])), \
                mock.patch.object(apps, "_run_batches") as run_batches:
            status = apps.get_status_label_map()
            self.assertEqual(status["vlc"], "Error")
            self.assertEqual(status["git"], "Not installed")
            for operation in (apps.install_apps, apps.update_apps, apps.uninstall_apps):
                result = operation(["vlc"], "flatpak", log=self.log)
                self.assertFalse(result.ok)
                self.assertIn("Cannot determine installed state", result.message)
                self.assertIn(warning, result.details)
            run_batches.assert_not_called()

    def test_dashboard_failed_measurements_are_unavailable_not_zero(self):
        with mock.patch.object(dashboard, "psutil", None), \
                mock.patch.object(dashboard, "_fallback_cpu", return_value=None), \
                mock.patch.object(dashboard, "_fallback_memory", return_value=(None, None, None)), \
                mock.patch.object(dashboard, "_fallback_swap", return_value=(None, None, None)), \
                mock.patch.object(dashboard.os, "statvfs", side_effect=OSError("unavailable")):
            info = dashboard.get_system_info()
        for key in ("cpu_percent", "mem_percent", "disk_percent", "swap_percent"):
            self.assertEqual(info[key], "Unavailable")
        self.assertEqual(info["disk_used"], "Unavailable")

    def test_missing_flatpak_does_not_block_known_apt_operations(self):
        with mock.patch.object(apps, "get_installed_state",
                               return_value=(set(), {"vlc"}, ["flatpak is not installed"])), \
                mock.patch.object(apps, "_run_batches"):
            outcome = apps.uninstall_apps(["vlc"], "apt", log=self.log)
            self.assertTrue(outcome.ok)

    def test_manage_scan_reports_failed_flatpak_with_exit_detail(self):
        warnings = []
        with mock.patch.object(apps, "has_command", return_value=True), \
                mock.patch.object(apps, "run_cmd",
                                  return_value=utils.CommandResult(23, "", "flatpak database error")):
            self.assertEqual(apps.list_installed_flatpak(warnings, self.log), [])
        self.assertIn("exit 23", warnings[0])
        self.assertIn("flatpak database error", self.log.text())

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

    def test_update_and_uninstall_selected_use_installed_formats_once(self):
        self.fake.update(flatpaks=["org.videolan.VLC"], apt={"vlc": "install ok installed"})
        for operation, flatpak_action, apt_action in (
                (apps.update_apps, "update", "--only-upgrade"),
                (apps.uninstall_apps, "uninstall", "remove")):
            with self.subTest(operation=operation.__name__):
                self.fake.clear_log()
                apps.invalidate_state()
                result = operation(["vlc", "vlc"], "apt", log=self.log)
                self.assertTrue(result.ok, result.message)
                flatpak_calls = [c for c in self.fake.commands() if c["cmd"] == "flatpak" and
                                 c["args"] and c["args"][0] == flatpak_action]
                self.assertEqual(len(flatpak_calls), 1)
                self.assertEqual(flatpak_calls[0]["args"].count("org.videolan.VLC"), 1)
                apt_calls = [c for c in self.fake.commands() if c["cmd"] in ("pkexec", "bash")]
                self.assertEqual(len(apt_calls), 1)
                self.assertIn(apt_action, apt_calls[0]["args"][-1])

    def test_update_all_dispatches_the_selected_source(self):
        for source in ("flatpak", "apt"):
            with self.subTest(source=source):
                self.fake.clear_log()
                result = apps.update_all(source, log=self.log)
                self.assertTrue(result.ok, result.message)
                commands = self.fake.mutating_commands()
                self.assertEqual(len(commands), 1)
                if source == "flatpak":
                    self.assertEqual(commands[0]["cmd"], "flatpak")
                    self.assertEqual(commands[0]["args"][0], "update")
                else:
                    self.assertIn("apt-get upgrade -y", commands[0]["args"][-1])

    def test_flathub_failure_still_runs_unrelated_apt_fallback_and_reports_partial_failure(self):
        with mock.patch.object(apps, "ensure_flathub", return_value=False):
            result = apps.install_apps(["spotify", "git"], "flatpak", log=self.log)
        self.assertFalse(result.ok)
        self.assertIn("flathub", " ".join(result.details))
        calls = self.fake.mutating_commands()
        self.assertTrue(any(c["cmd"] in ("pkexec", "bash") and
                            "apt-get install -y git" in c["args"][-1] for c in calls))
        self.assertFalse(any(c["cmd"] == "flatpak" and c["args"][0] == "install" for c in calls))

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
    # Snap support in Manage Apps
    # ------------------------------------------------------------------
    def test_snap_scanner_lists_apps_and_protects_base(self):
        self.fake.update(snaps={
            "firefox": {"version": "125.0", "notes": "-"},
            "core22": {"version": "20240408", "notes": "base"},
            "snapd": {"version": "2.63", "notes": "snapd"},
            "oldapp": {"version": "1.0", "notes": "disabled"},
        })
        entries = apps.list_installed_snap()
        by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(set(by_id), {"firefox", "core22", "snapd"})
        self.assertFalse(by_id["firefox"]["protected"])
        self.assertTrue(by_id["core22"]["protected"])
        self.assertTrue(by_id["snapd"]["protected"])
        self.assertEqual(by_id["firefox"]["source"], "snap")
        self.assertEqual(by_id["firefox"]["version"], "125.0")

    def test_snap_scanner_is_silent_when_snapd_is_missing(self):
        warnings: list = []
        with mock.patch.object(apps, "has_command", return_value=False):
            entries = apps.list_installed_snap(warnings=warnings)
        self.assertEqual(entries, [])
        self.assertEqual(warnings, [])

    def test_snap_uninstall_runs_polkit_remove(self):
        outcome = apps.uninstall_installed([{"source": "snap", "id": "firefox"}], log=self.log)
        self.assertTrue(outcome.ok)
        script = self.fake.mutating_commands()[-1]["args"][2]
        self.assertIn("snap remove firefox", script)
        self.assertIn("0 Flatpak app(s), 0 APT package(s) and 1 snap(s)", outcome.message)

    def test_base_snaps_refuse_removal(self):
        outcome = apps.uninstall_installed([{"source": "snap", "id": "core22"}], log=self.log)
        self.assertFalse(outcome.ok)
        self.assertEqual(self.fake.mutating_commands(), [])
        self.assertIn("base snap", self.log.text())

    def test_mixed_uninstall_batches_every_source(self):
        outcome = apps.uninstall_installed([
            {"source": "flatpak", "id": "com.spotify.Client"},
            {"source": "apt", "id": "vlc"},
            {"source": "snap", "id": "firefox"},
        ], log=self.log)
        self.assertTrue(outcome.ok)
        scripts = [c["args"][2] for c in self.fake.mutating_commands() if c["cmd"] == "pkexec"]
        self.assertTrue(any("apt-get remove -y vlc" in script for script in scripts))
        self.assertTrue(any("snap remove firefox" in script for script in scripts))
        self.assertTrue(any(c["cmd"] == "flatpak" and "uninstall" in c["args"]
                            for c in self.fake.commands()))

    def test_list_updates_parses_all_three_sources(self):
        self.fake.update(apt_upgradable=["vlc", "git"],
                         flatpak_updates=["com.spotify.Client", "org.videolan.VLC"],
                         snap_updates={"firefox": {"version": "126.0"}})
        updates = apps.list_updates()
        self.assertEqual(updates["apt"], {"vlc", "git"})
        self.assertEqual(updates["flatpak"], {"com.spotify.Client", "org.videolan.VLC"})
        self.assertEqual(updates["snap"], {"firefox"})

    def test_list_updates_downgrades_failures_to_warnings(self):
        self.fake.update(flatpak_remote_ls_fail=True)
        warnings: list = []
        updates = apps.list_updates(warnings=warnings)
        self.assertEqual(updates["apt"], set())
        self.assertEqual(updates["flatpak"], set())
        self.assertTrue(any("Flatpak update check failed" in w for w in warnings))

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
            lambda: apps.uninstall_installed([{"source": "snap", "id": "firefox"}], log=self.log),
            lambda: maintenance.set_schedule(True, "weekly", log=self.log),
            lambda: drivers.install_driver(["nvidia-driver-535"], log=self.log),
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
            lambda: ui_customization.set_text_scaling(1.25, log=self.log),
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
        for profile in performance.POWER_PROFILES:
            with self.subTest(profile=profile):
                self.fake.clear_log()
                self.assertTrue(performance.set_power_profile(profile, log=self.log).ok)
                self.assertEqual(self.fake.mutating_commands()[-1]["args"], ["set", profile])

    def test_all_gui_swap_sizes_produce_the_requested_safe_script(self):
        self.fake.update(swap=[])
        for size in (1, 2, 4, 8):
            with self.subTest(size=size):
                self.fake.clear_log()
                self.assertTrue(performance.enable_swapfile(size, log=self.log).ok)
                command = next(c for c in self.fake.commands() if c["cmd"] in ("pkexec", "bash"))
                self.assertIn("fallocate -l {}G".format(size), command["args"][-1])

    def test_swap_enable_refuses_existing_inactive_files_and_links(self):
        self.fake.update(swap=[])
        self.swapfile.write_bytes(b"important data")
        result = performance.enable_swapfile(2, log=self.log)
        self.assertFalse(result.ok)
        self.assertIn("will not overwrite", result.message)
        self.assertEqual(self.swapfile.read_bytes(), b"important data")
        self.assertFalse(self.fake.mutating_commands())
        self.swapfile.unlink()
        self.swapfile.symlink_to(self.root / "missing")
        self.assertFalse(performance.enable_swapfile(2).ok)
        self.assertFalse(performance.disable_swapfile().ok)
        self.assertFalse(self.fake.mutating_commands())
        self.swapfile.unlink()
        self.assertTrue(performance.enable_swapfile(2, log=self.log).ok)
        script = [c for c in self.fake.commands() if c["cmd"] in ("pkexec", "bash")][-1]["args"][-1]
        self.assertIn("set -C", script)
        self.assertIn("refusing to overwrite", script)

    def test_failed_swap_setup_removes_only_its_new_temporary_file(self):
        self.fake.update(swap=[])
        self.assertTrue(performance.enable_swapfile(2, log=self.log).ok)
        script = [c for c in self.fake.commands() if c["cmd"] in ("pkexec", "bash")][-1]["args"][-1]
        tools = self.root / "safe-tools"
        tools.mkdir()
        for name, exit_code in (("fallocate", 0), ("mkswap", 7)):
            path = tools / name
            path.write_text("#!/bin/sh\nexit {}\n".format(exit_code), encoding="utf-8")
            path.chmod(0o755)
        result = subprocess.run(["/bin/bash", "-c", script],
                                env={"PATH": str(tools) + ":/usr/bin:/bin"},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 7)
        self.assertFalse(self.swapfile.exists())
        self.assertIn("activated=1", script)
        self.assertIn("trap cleanup_new_swap EXIT", script)

    def test_custom_zram_config_is_never_replaced_or_removed(self):
        custom = "[zram0]\nzram-size = ram\n# my settings\n"
        self.zram_cfg.write_text(custom, encoding="utf-8")
        self.fake.update(swap=[])
        self.assertFalse(performance.enable_zram(log=self.log).ok)
        self.assertFalse(performance.disable_zram(log=self.log).ok)
        self.assertEqual(self.zram_cfg.read_text(encoding="utf-8"), custom)
        self.assertFalse(self.fake.mutating_commands())
        self.zram_cfg.unlink()
        self.zram_cfg.symlink_to(self.root / "missing")
        self.assertFalse(performance.enable_zram().ok)
        self.assertFalse(performance.disable_zram().ok)
        self.zram_cfg.unlink()
        self.zram_cfg.write_text(performance._LEGACY_ZRAM_CONFIG, encoding="utf-8")
        self.assertTrue(performance.enable_zram(log=self.log).ok)
        self.assertTrue(performance.disable_zram(log=self.log).ok)
        scripts = [c["args"][-1] for c in self.fake.commands() if c["cmd"] in ("pkexec", "bash")]
        self.assertEqual(len(scripts), 2)
        self.assertTrue(all("not managed by Preen" in script for script in scripts))
        for script in scripts:
            result = subprocess.run(["/bin/bash", "-n", "-c", script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_autostart_toggle_removes_conflicting_duplicate_keys(self):
        path = self.user_autostart / "duplicates.desktop"
        path.write_text("[Desktop Entry]\nType=Application\nName=Demo\nExec=demo\n"
                        "Hidden=false\nHidden=true\nX-GNOME-Autostart-enabled=false\n"
                        "X-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        self.assertTrue(system.set_startup_app(str(path), True).ok)
        content = path.read_text(encoding="utf-8")
        self.assertEqual(content.count("Hidden="), 1)
        self.assertEqual(content.count("X-GNOME-Autostart-enabled="), 1)
        self.assertTrue(system.list_startup_apps()[0]["enabled"])

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

    def test_archive_restore_does_not_create_group_or_world_writable_files(self):
        archive = self.root / "permissive.tar"
        with tarfile.open(archive, "w") as tar:
            payload = b"test"
            member = tarfile.TarInfo(".config/writable.txt")
            member.size = len(payload)
            member.mode = 0o7777
            tar.addfile(member, io.BytesIO(payload))
        self.assertTrue(backup.import_configs(str(archive)).ok)
        mode = (self.config_dir / "writable.txt").stat().st_mode
        self.assertEqual(mode & 0o7022, 0)

    def test_config_restore_refuses_preexisting_symlink_destinations(self):
        outside = self.root / "outside"
        outside.mkdir()
        victim = outside / "victim.ini"
        victim.write_text("keep", encoding="utf-8")
        archive = self.root / "links.tar"
        self._make_archive(archive, [(".config/linked/victim.ini", "file", "overwritten")])
        (self.config_dir / "linked").symlink_to(outside, target_is_directory=True)
        count, rejected = backup.inspect_archive(str(archive))
        self.assertEqual(count, 1)
        self.assertTrue(rejected)
        self.assertFalse(backup.import_configs(str(archive)).ok)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")
        # Even if a link appears after preflight, descriptor-based extraction
        # refuses to follow it on Python versions lacking tarfile filters.
        with mock.patch.object(backup, "_destination_conflicts", return_value=[]):
            self.assertFalse(backup.import_configs(str(archive)).ok)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

        (self.config_dir / "linked").unlink()
        (self.config_dir / "linked").mkdir()
        (self.config_dir / "linked" / "victim.ini").symlink_to(victim)
        self.assertFalse(backup.import_configs(str(archive)).ok)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

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

    def test_nested_icon_theme_keeps_existing_theme_as_backup(self):
        existing = self.fake.icons_dir / "MyIcons"
        existing.mkdir()
        (existing / "old.png").write_bytes(b"keep")
        archive = self.root / "nested-icons.tar"
        self._make_archive(archive, [
            ("wrapper/MyIcons/index.theme", "file", "[Icon Theme]\nName=MyIcons\n"),
            ("wrapper/MyIcons/new.png", "file", b"new"),
        ])
        outcome = ui_customization.install_icon_pack(str(archive), log=self.log)
        self.assertTrue(outcome.ok, outcome.message)
        self.assertTrue((existing / "index.theme").exists())
        self.assertTrue((existing / "new.png").exists())
        backups = list((self.fake.icons_dir / ".preen-backups").glob("MyIcons-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "old.png").read_bytes(), b"keep")
        self.assertIn(str(backups[0]), self.log.text())
        self.assertIn("MyIcons", self.fake.commands()[-1]["args"])

    def test_icon_install_without_gsettings_does_not_claim_activation(self):
        archive = self.root / "Standalone.tar"
        self._make_archive(archive, [("index.theme", "file", "[Icon Theme]\nName=Standalone\n")])
        with mock.patch.object(ui_customization, "has_command", return_value=False):
            outcome = ui_customization.install_icon_pack(str(archive), log=self.log)
        self.assertTrue(outcome.ok)
        self.assertIn("could not activate", outcome.message)
        self.assertTrue((self.fake.icons_dir / "Standalone" / "index.theme").exists())

    def test_rounded_corners_css_is_idempotent_and_removable(self):
        self.assertTrue(ui_customization.set_rounded_corners(True, log=self.log).ok)
        self.assertTrue(ui_customization.set_rounded_corners(True, log=self.log).ok)
        css = (self.css_dir / "gtk.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS"), 1)
        self.assertTrue(ui_customization.set_rounded_corners(False, log=self.log).ok)
        self.assertNotIn("BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS",
                         (self.css_dir / "gtk.css").read_text(encoding="utf-8"))

    def test_incomplete_rounded_corners_marker_preserves_user_css(self):
        self.css_dir.mkdir(exist_ok=True)
        path = self.css_dir / "gtk.css"
        original = "label { color: red; }\n" + ui_customization.START_GUARD + "user rules\n"
        path.write_text(original, encoding="utf-8")
        self.assertFalse(ui_customization.set_rounded_corners(False).ok)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

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
        self.assertTrue(any("Drivers page" in w for w in warnings))
        self.assertTrue(any("firewall toggle" in w for w in warnings))

    def test_dashboard_works_without_psutil(self):
        with mock.patch.object(dashboard, "psutil", None):
            info = dashboard.get_system_info()
        for key in ("cpu_percent", "mem_percent", "disk_percent", "os", "kernel", "uptime"):
            self.assertIn(key, info)

    def test_dashboard_reports_swap_and_load_average(self):
        info = dashboard.get_system_info()
        for key in ("swap_percent", "swap_used", "load_average"):
            self.assertIn(key, info)
        float(str(info["swap_percent"]).rstrip("%"))  # numeric, percent formatted

    def test_text_scaling_is_validated_simulate_gated_and_applied(self):
        # Out of range: refused before any command runs.
        self.assertFalse(ui_customization.set_text_scaling(5.0, log=self.log).ok)
        self.assertEqual(self.fake.mutating_commands(), [])

        # Simulate: no gsettings set is spawned.
        utils.set_simulate(True)
        outcome = ui_customization.set_text_scaling(1.25, log=self.log)
        self.assertTrue(outcome.ok)
        self.assertEqual(self.fake.mutating_commands(), [])
        utils.set_simulate(False)

        # Real run: the factor is written through gsettings.
        outcome = ui_customization.set_text_scaling(1.15, log=self.log)
        self.assertTrue(outcome.ok)
        sets = [c for c in self.fake.commands()
                if c["cmd"] == "gsettings" and c["args"][:2] == ["set", "org.gnome.desktop.interface"]]
        self.assertTrue(any("text-scaling-factor" in c["args"] for c in sets))

        # An unreadable value must not silently become a real 100% setting.
        with mock.patch.object(ui_customization, "run_cmd",
                               return_value=utils.CommandResult(0, "not-a-number\n", "")):
            self.assertIsNone(ui_customization.get_text_scaling())

    def test_snapshot_list_is_parsed_into_plain_dicts(self):
        sample = (
            "Local @ /\n"
            "Num     Name                 Tags  Description        Date\n"
            "0       2024-01-15_10-00-00   D     daily snapshot     2024-01-15 10:00:01\n"
            "1       2024-01-14_10-00-00   B                        2024-01-14 10:00:01\n"
            "junk line that must be ignored\n"
        )
        snapshots = backup.parse_snapshot_list(sample)
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0]["name"], "2024-01-15_10-00-00")
        self.assertEqual(snapshots[0]["tags"], "D")
        self.assertEqual(snapshots[0]["description"], "daily snapshot")
        self.assertEqual(snapshots[0]["date"], "2024-01-15 10:00:01")
        self.assertEqual(snapshots[1]["description"], "")
        self.assertEqual(snapshots[1]["date"], "2024-01-14 10:00:01")
        marked = backup.parse_snapshot_list(
            "0  >  2025-01-01_09-00-00  O  Before update\n"
            "1  >  2025-01-02_10-00-00  D\n")
        self.assertEqual([row["name"] for row in marked],
                         ["2025-01-01_09-00-00", "2025-01-02_10-00-00"])
        self.assertEqual(marked[0]["description"], "Before update")
        self.assertEqual(marked[1]["description"], "")
        self.assertEqual(backup.parse_snapshot_list(""), [])

    def test_timeshift_failure_is_not_an_empty_snapshot_list_or_privilege_prompt(self):
        self.fake.update(timeshift_exit=1, timeshift_error="root access required")
        self.assertIsNone(backup.list_snapshots(log=self.log))
        self.assertIn("root access required", self.log.text())
        self.assertIn("exit 1", self.log.text())
        self.assertFalse(self.fake.mutating_commands())
        self.fake.update(timeshift_exit=1, timeshift_error="", timeshift_list="No snapshots found\n")
        self.assertEqual(backup.list_snapshots(log=self.log), [])
        self.fake.update(timeshift_exit=0, timeshift_error="", timeshift_list="")
        self.assertEqual(backup.list_snapshots(log=self.log), [])

    def test_manual_snapshot_uses_on_demand_tag(self):
        with mock.patch.object(utils.os, "geteuid", return_value=1000):
            result = backup.timeshift_snapshot("Before testing", log=self.log)
        self.assertTrue(result.ok)
        command = next(c for c in self.fake.commands() if c["cmd"] == "pkexec")
        self.assertEqual(command["args"][-2:], ["--tags", "O"])

    def test_manual_snapshot_refresh_uses_polkit_only_when_requested(self):
        self.fake.clear_log()
        with mock.patch.object(utils.os, "geteuid", return_value=1000):
            self.assertEqual(backup.list_snapshots(privileged=True, log=self.log), [])
        self.assertTrue(any(c["cmd"] == "pkexec" and c["args"] == ["timeshift", "--list"]
                            for c in self.fake.commands()))
        self.fake.clear_log()
        utils.set_simulate(True)
        self.assertIsNone(backup.list_snapshots(privileged=True, log=self.log))
        self.assertFalse(self.fake.mutating_commands())
        self.assertIn("[simulate]", self.log.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
