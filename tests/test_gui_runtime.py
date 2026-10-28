"""Runtime GUI smoke test using a fake GTK.

PyGObject is not available in this environment, so this walks the entire
MainWindow construction path and clicks most handlers with stand-in widgets.
It catches typos, missing attributes and bad call signatures that an
import-only test cannot.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preen_tool.backend import settings as settings_backend  # noqa: E402
from preen_tool.backend import utils  # noqa: E402


class FakeTextBuffer:
    def __init__(self):
        self.text = ""

    def get_end_iter(self):
        return object()

    def get_start_iter(self):
        return object()

    def get_iter_at_line(self, _line):
        return object()

    def get_line_count(self):
        return 1

    def insert(self, _where, text):
        self.text += text

    def delete(self, *_args):
        return None

    def create_mark(self, *_args):
        return object()

    def delete_mark(self, *_args):
        return None

    def set_text(self, text):
        self.text = text


class FakeStyleContext:
    def add_class(self, _name):
        return None

    def remove_class(self, _name):
        return None

    def add_provider(self, *_args):
        return None


class Widget:
    """Every GTK widget is one of these; unknown methods are harmless no-ops."""

    def __init__(self, *args, **kwargs):
        self._children = []
        self._handlers = {}
        self._texts = []
        self._active = 0
        self._text = kwargs.get("label", kwargs.get("title", "")) or ""
        self._sensitive = True
        self._visible = False
        self._no_show_all = False
        self._buffer = FakeTextBuffer()
        self.chk = None
        self.entry = None
        self.search_text = ""
        self.is_header = False
        self.app_id = None
        self.status_label = None

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None

    @classmethod
    def new_with_label(cls, label):
        return cls(label=label)

    # widget tree
    def add(self, child):
        self._children.append(child)

    def pack_start(self, child, *_args):
        self._children.append(child)

    def pack_end(self, child, *_args):
        self._children.append(child)

    def attach(self, child, *_args):
        self._children.append(child)

    def add_titled(self, child, *_args):
        self._children.append(child)

    def get_children(self):
        return list(self._children)

    def set_no_show_all(self, value):
        self._no_show_all = bool(value)

    def show(self):
        self._visible = True

    def hide(self):
        self._visible = False

    def set_visible(self, value):
        self._visible = bool(value)

    def get_visible(self):
        return self._visible

    def show_all(self):
        if self._no_show_all:
            return
        self.show()
        for child in self._children:
            child.show_all()

    def remove(self, child):
        if isinstance(child, int) and 0 <= child < len(self._texts):
            self._texts.pop(child)
        elif child in self._children:
            self._children.remove(child)

    def get_content_area(self):
        return self

    def get_buffer(self):
        return self._buffer

    def get_style_context(self):
        return FakeStyleContext()

    # values
    def connect(self, signal, handler, *_args):
        self._handlers.setdefault(signal, []).append(handler)
        return 1

    def append_text(self, text):
        self._texts.append(text)

    def set_active(self, index):
        self._active = index

    def get_active(self):
        return self._active

    def get_active_text(self):
        if 0 <= self._active < len(self._texts):
            return self._texts[self._active]
        return None

    def set_text(self, text):
        self._text = text

    def set_markup(self, markup):
        self._text = markup

    def get_text(self):
        return self._text

    def set_sensitive(self, value):
        self._sensitive = value

    def get_sensitive(self):
        return self._sensitive

    def get_filename(self):
        return None

    def set_filter_func(self, func, _data=None):
        self._filter = func

    def run(self):
        # CANCEL: dialogs never approve a destructive action in this test.
        return -6

    def destroy(self):
        return None


class FakeImage(Widget):
    """Gtk.Image needs a class-level constructor the plain Widget lacks."""

    @classmethod
    def new_from_icon_name(cls, *_args):
        return cls()


class FakeToggleButton(Widget):
    """GTK 3 may emit clicked from set_active, not just on pointer clicks."""

    def set_active(self, value):
        changed = bool(value) != bool(self._active)
        self._active = bool(value)
        if changed:
            for handler in self._handlers.get("clicked", []):
                handler(self)

    def clicked(self):
        self.set_active(not self.get_active())


class FakeCssProvider(Widget):
    def load_from_data(self, css):
        self.css = css


class FakeGtk:
    ApplicationWindow = Widget
    Application = Widget
    Box = Widget
    Button = Widget
    ToggleButton = FakeToggleButton
    CheckButton = Widget
    ComboBoxText = Widget
    Dialog = Widget
    FileChooserDialog = Widget
    Grid = Widget
    HeaderBar = Widget
    Image = FakeImage
    Label = Widget
    ListBox = Widget
    ListBoxRow = Widget
    MessageDialog = Widget
    ProgressBar = Widget
    ScrolledWindow = Widget
    SearchEntry = Widget
    Separator = Widget
    Stack = Widget
    StackSidebar = Widget
    Switch = Widget
    TextView = Widget
    TextBuffer = FakeTextBuffer
    InfoBar = Widget
    Spinner = Widget
    Frame = Widget
    AboutDialog = Widget
    CssProvider = FakeCssProvider

    class StyleContext:
        @staticmethod
        def add_provider_for_screen(*_args):
            return None

    Orientation = SimpleNamespace(HORIZONTAL=0, VERTICAL=1)
    SelectionMode = SimpleNamespace(NONE=0, SINGLE=1)
    PolicyType = SimpleNamespace(NEVER=0, AUTOMATIC=1, ALWAYS=2)
    Align = SimpleNamespace(CENTER=3, START=0)
    StackTransitionType = SimpleNamespace(CROSSFADE=0)
    MessageType = SimpleNamespace(INFO=0, WARNING=1, ERROR=2)
    ButtonsType = SimpleNamespace(CLOSE=1, OK_CANCEL=2)
    ResponseType = SimpleNamespace(OK=-5, CANCEL=-6, CLOSE=-7, APPLY=-10)
    FileChooserAction = SimpleNamespace(OPEN=0, SAVE=1)
    Justification = SimpleNamespace(LEFT=0)
    WrapMode = SimpleNamespace(NONE=0, WORD_CHAR=2)
    STOCK_CANCEL = "gtk-cancel"
    STOCK_OPEN = "gtk-open"
    STOCK_SAVE = "gtk-save"
    STOCK_APPLY = "gtk-apply"

    def __getattr__(self, _name):
        return Widget


class FakeGLib:
    @staticmethod
    def idle_add(func, *args):
        func(*args)
        return 1

    @staticmethod
    def timeout_add_seconds(_interval, _func):
        return 1  # do not start a live timer in the test


class _Gi(types.ModuleType):
    def require_version(self, *_args):
        return None


class SyncThread:
    def __init__(self, target=None, daemon=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class GuiRuntimeTest(unittest.TestCase):
    def setUp(self):
        gi = _Gi("gi")
        repo = types.ModuleType("gi.repository")
        repo.Gtk = FakeGtk()
        repo.GLib = FakeGLib()
        repo.Gio = SimpleNamespace(SettingsSchemaSource=SimpleNamespace(get_default=lambda: None))
        repo.Gdk = SimpleNamespace(
            Screen=SimpleNamespace(get_default=lambda: object()))
        repo.Pango = SimpleNamespace(
            EllipsizeMode=SimpleNamespace(END=3, MIDDLE=2, START=1))
        gi.repository = repo
        self.patch = mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repo})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        sys.modules.pop("preen_tool.gui", None)
        self.gui = importlib.import_module("preen_tool.gui")
        self.addCleanup(lambda: sys.modules.pop("preen_tool.gui", None))
        self.simulate_patch = mock.patch.object(utils, "_simulate", True)
        self.simulate_patch.start()
        self.addCleanup(self.simulate_patch.stop)
        self.thread_patch = mock.patch.object(self.gui.threading, "Thread", SyncThread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)
        # Keep preferences/reads inside a temporary directory.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_dir = Path(tmp.name) / "zorin-optimizer"
        for target, value in (("CONFIG_DIR", str(settings_dir)),
                              ("SETTINGS_PATH", str(settings_dir / "settings.json"))):
            patch = mock.patch.object(settings_backend, target, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_window_builds_and_all_pages_exist(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self.assertEqual(len(window.stack.get_children()), 9)
        self.assertIn("code", window.app_rows)
        self.assertTrue(window.log_buf.lines)
        # New 0.4.0 surfaces.
        self.assertEqual(set(window.stat_bars), {"cpu", "mem", "disk", "swap"})
        self.assertTrue(window.install_source.buttons)
        self.assertIn(window.install_source.get_active_text(), ("Flatpak", "APT"))
        self.assertTrue(hasattr(window, "snapshot_listbox"))
        self.assertTrue(hasattr(window, "log_filter"))
        self.assertTrue(hasattr(window, "chk_running_only"))
        self.assertTrue(hasattr(window, "cmb_swap_size"))
        self.assertTrue(hasattr(window, "cmb_scaling"))
        # Four non-selectable section headers plus nine page rows.
        section_rows = [r for r in window.sidebar_list.get_children()
                        if getattr(r, "page_name", False) is None]
        self.assertEqual(len(section_rows), 4)

    def test_startup_prioritizes_reading_appearance_before_package_scans(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(window, "submit") as submit:
            window._start_initial_tasks()
        self.assertEqual(submit.call_args_list[0].args[0], window._read_settings)

    def test_snapshot_refresh_keeps_export_and_import_controls(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        callbacks = [handler.__name__ for button in window.action_widgets
                     for handler in button._handlers.get("clicked", [])]
        self.assertIn("on_export_config", callbacks)
        self.assertIn("on_import_config", callbacks)
        window._apply_snapshots([])
        self.assertTrue(window.snapshot_empty.get_visible())
        window._apply_snapshots([{"name": "snapshot-1", "date": "today", "tags": "D"}])
        self.assertFalse(window.snapshot_empty.get_visible())
        self.assertEqual(len(window.snapshot_listbox.get_children()), 1)
        window.submit(lambda: [], done=window._apply_snapshots)
        self.assertEqual(len(window.snapshot_listbox.get_children()), 0)
        self.assertIn("No snapshots found", window.snapshot_empty.get_text())
        window._apply_snapshots(None)
        self.assertIn("unavailable", window.snapshot_empty.get_text().lower())
        self.assertNotIn("UI update failed", "".join(window.log_buf.lines))

    def test_busy_queue_is_serial_and_locks_simulation_until_callbacks_finish(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        events = []

        def first():
            events.append("first")
            return "read"

        def finished(_result):
            events.append(("callback", window._busy, window.sim_switch.get_sensitive()))
            window.submit(lambda: events.append("second"))
            events.append("callback end")

        window.submit(first, done=finished)
        self.assertEqual(events, ["first", ("callback", True, False), "callback end", "second"])
        self.assertFalse(window._busy)
        self.assertTrue(window.sim_switch.get_sensitive())
        self.assertFalse(window.busy_box.get_visible())

    def test_destructive_confirmation_remains_required_when_preference_is_off(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window.settings["confirm_destructive"] = False
        # Fake dialogs cancel; only the optional full-update prompt can be skipped.
        self.assertFalse(window._confirm("Remove?", "Permanent", required=True))
        self.assertTrue(window._confirm("Update all?", "Optional", required=False))

    def test_unavailable_dashboard_metric_hides_its_progress_bar(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_stats({"cpu_percent": "Unavailable", "cpu_cores": "Unavailable"})
        self.assertEqual(window.stat_bars["cpu"][0].get_text(), "—")
        self.assertFalse(window.stat_bars["cpu"][1].get_visible())
        window._apply_stats({"cpu_percent": "12.5", "cpu_cores": "2"})
        self.assertTrue(window.stat_bars["cpu"][1].get_visible())

    def test_environment_forced_simulation_stays_visible_and_locked(self):
        with mock.patch.dict("os.environ", {utils.SIMULATE_ENV: "1"}):
            window = self.gui.MainWindow(self.gui.PreenApp())
            self.assertTrue(window.sim_switch.get_active())
            self.assertTrue(window.sim_banner.get_visible())
            self.assertFalse(window.sim_switch.get_sensitive())
            window.sim_switch.set_active(False)
            window.on_toggle_simulate(window.sim_switch, None)
            self.assertTrue(window.sim_switch.get_active())
            self.assertTrue(utils.is_simulate())

    def test_callback_failure_keeps_traceback_and_error_banner(self):
        window = self.gui.MainWindow(self.gui.PreenApp())

        def broken(_value):
            raise NameError("specific callback bug")

        window.submit(lambda: "read", done=broken)
        log = "".join(window.log_buf.lines)
        self.assertIn("UI update failed", log)
        self.assertIn("Traceback", log)
        self.assertIn("specific callback bug", log)
        self.assertEqual(window._banner_level, "error")
        window._notify("Later success", "info")
        self.assertNotEqual(window.banner_label.get_text(), "Later success")
        self.assertTrue(window.banner.get_visible())
        self.assertTrue(window.banner_label.get_visible())
        window._dismiss_banner()
        window._notify("Later success", "info")
        self.assertEqual(window.banner_label.get_text(), "Later success")

    def test_health_warning_and_power_profile_reflect_real_availability(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        settings = {"animations_off": False, "swap": False, "zram": False,
                    "power": "", "theme": "light", "round": False,
                    "scaling": 1.0, "warnings": ["Tool missing"]}
        window._apply_settings(settings)
        self.assertTrue(window.health_box.get_visible())
        self.assertIn("Tool missing", window.lbl_health.get_text())
        self.assertEqual(window.cmb_power.get_active_text(), "Unavailable")
        self.assertFalse(window.cmb_power.get_sensitive())
        with mock.patch.object(window, "submit") as submit:
            window.on_run_optimize(None)
            submit.assert_not_called()
        settings = dict(settings, power="balanced", warnings=[])
        window._apply_settings(settings)
        self.assertFalse(window.health_box.get_visible())
        self.assertTrue(window.cmb_power.get_sensitive())
        window.cmb_power.set_active(self.gui.perf_backend.POWER_PROFILES.index("performance"))
        with mock.patch.object(window, "submit") as submit:
            window.on_run_optimize(None)
            actions = submit.call_args.args[1]
            self.assertEqual([action[0] for action in actions], ["Power profile"])

    def test_segmented_source_handles_recursive_gtk_toggle_signals_once(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        source = window.install_source
        changed = mock.Mock()
        source.on_changed = changed
        source.buttons[1].clicked()
        self.assertEqual(source.get_active_text(), "APT")
        self.assertFalse(source.buttons[0].get_active())
        self.assertTrue(source.buttons[1].get_active())
        changed.assert_called_once()
        source.buttons[1].clicked()  # selected item stays selected, no refresh
        self.assertEqual(source.get_active_text(), "APT")
        self.assertTrue(source.buttons[1].get_active())
        changed.assert_called_once()
        source.set_active(0)  # preference restore is not a user click
        self.assertEqual(source.get_active_text(), "Flatpak")
        changed.assert_called_once()

    def test_startup_app_scan_runs_in_worker_before_showing_dialog(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(self.gui.system_backend, "list_startup_apps") as scan:
            window.on_manage_startup(None)
            scan.assert_not_called()
            self.assertIs(submit.call_args.args[0], scan)
            self.assertEqual(submit.call_args.kwargs["done"], window._show_startup_dialog)

    def test_backup_inspection_is_queued_and_unsafe_archives_are_not_confirmed(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(window, "_open_dialog", return_value="/tmp/config.tar"), \
                mock.patch.object(window, "submit") as submit, \
                mock.patch.object(self.gui.backup_backend, "inspect_archive") as inspect, \
                mock.patch.object(window, "_confirm", return_value=True) as confirm:
            window.on_import_config(None)
            inspect.assert_not_called()  # inspection is handed to the worker
            self.assertIs(submit.call_args.args[0], inspect)
            callback = submit.call_args.kwargs["done"]
            submit.reset_mock()
            callback((1, ["unsafe symlink"]))
            confirm.assert_not_called()
            submit.assert_not_called()
            self.assertIn("Nothing was restored", window.banner_label.get_text())
            window._dismiss_banner()
            callback((2, []))
            confirm.assert_called_once()
            self.assertIs(submit.call_args.args[0], self.gui.backup_backend.import_configs)

    def test_theme_changes_palette_without_discarding_other_staged_settings(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": False, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window._css_provider.css, self.gui._LIGHT_CSS)
        window.chk_animations.set_active(True)
        window.chk_round.set_active(True)
        window.cmb_scaling.set_active(2)
        window.cmb_theme.set_active(1)
        with mock.patch.object(utils, "_simulate", False), \
                mock.patch.object(self.gui.ui_backend, "apply_theme_mode",
                                  return_value=utils.ok("Applied")) as apply, \
                mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"):
            window.on_apply_theme(None)
        apply.assert_called_once()
        self.assertEqual(window._app_theme, "dark")
        self.assertEqual(window._css_provider.css, self.gui._CSS)
        self.assertTrue(window.chk_animations.get_active())
        self.assertTrue(window.chk_round.get_active())
        self.assertEqual(window.cmb_scaling.get_active(), 2)
        self.assertEqual(window.baseline["scaling"], 1.0)
        self.assertFalse(window.baseline["round"])

    def test_snapshot_refresh_requests_authorization_only_on_explicit_click(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(utils, "_simulate", False), mock.patch.object(window, "submit") as submit:
            window.on_refresh_snapshots(None)
            self.assertIs(submit.call_args.args[0], self.gui.backup_backend.list_snapshots)
            self.assertEqual(submit.call_args.args[1:], (True,))
        with mock.patch.object(utils, "_simulate", True), mock.patch.object(window, "submit") as submit:
            window.on_refresh_snapshots(None)
            submit.assert_not_called()
            self.assertIn("not refreshed", window.banner_label.get_text())
        with mock.patch.object(utils, "_simulate", False), mock.patch.object(window, "submit") as submit:
            window.on_snapshot(None)
            callback = submit.call_args.kwargs["done"]
            submit.reset_mock()
            callback(utils.ok("Snapshot requested"))
            submit.assert_not_called()  # no automatic second authentication prompt

    def test_theme_monitor_registers_only_available_gnome_keys(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        schema = SimpleNamespace(has_key=lambda key: key == "gtk-theme")
        source = SimpleNamespace(lookup=lambda _name, _recursive: schema)
        settings = mock.Mock()
        with mock.patch.object(self.gui.Gio.SettingsSchemaSource, "get_default", return_value=source), \
                mock.patch.object(self.gui.Gio, "Settings", create=True) as settings_type:
            settings_type.new_full.return_value = settings
            window._watch_desktop_appearance()
        settings.connect.assert_called_once_with("changed::gtk-theme", window._on_desktop_appearance_changed)

    def test_external_theme_change_updates_palette_without_losing_staged_choice(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_theme_setting("light")
        window.cmb_theme.set_active(1)  # user has staged Dark
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="light"):
            window._on_desktop_appearance_changed()
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window.cmb_theme.get_active_text(), "Dark")
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"):
            window._on_desktop_appearance_changed()
        self.assertEqual(window._app_theme, "dark")
        self.assertEqual(window.baseline["theme"], "dark")
        self.assertEqual(window.cmb_theme.get_active_text(), "Dark")

    def test_simulated_theme_keeps_actual_palette_and_can_be_retried(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_theme_setting("light")
        window.cmb_theme.set_active(1)
        with mock.patch.object(self.gui.ui_backend, "apply_theme_mode",
                               return_value=utils.ok("Simulation complete")), \
                mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="light"):
            window.on_apply_theme(None)
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window.cmb_theme.get_active_text(), "Light")
        self.assertEqual(window.baseline["theme"], "light")
        window.cmb_theme.set_active(1)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual(submit.call_args.args[1][0][0], "Theme")

    def test_custom_and_unreadable_scaling_are_never_silently_overwritten(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        info = {"theme": "light", "round": False, "scaling": 1.23}
        window._apply_look_settings(info)
        self.assertEqual(window.cmb_scaling.get_active_text(), "Custom (123%)")
        window.cmb_theme.set_active(1)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual([action[0] for action in submit.call_args.args[1]], ["Theme"])
        window.cmb_scaling.set_active(0)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual([action[0] for action in submit.call_args.args[1]], ["Theme", "Text size"])
        window._apply_look_settings(dict(info, scaling=None))
        self.assertEqual(window.cmb_scaling.get_active_text(), "Unavailable")
        self.assertFalse(window.cmb_scaling.get_sensitive())
        window.cmb_theme.set_active(1)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual([action[0] for action in submit.call_args.args[1]], ["Theme"])

    def test_optimize_builds_only_requested_actions_and_confirms_cleanup(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": False, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        window.chk_cleanup.set_active(True)
        window.chk_animations.set_active(True)
        window.chk_swap.set_active(True)
        window.cmb_swap_size.set_active(2)  # 4 GB
        window.chk_zram.set_active(True)
        window.cmb_power.set_active(self.gui.perf_backend.POWER_PROFILES.index("performance"))
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=True) as confirm:
            window.on_run_optimize(None)
            confirm.assert_called_once()
            actions = submit.call_args.args[1]
        self.assertEqual([item[0] for item in actions],
                         ["System cleanup", "GNOME animations", "Power profile", "Swapfile", "ZRAM"])
        self.assertEqual(actions[1][2], (False,))
        self.assertEqual(actions[2][2], ("performance",))
        self.assertEqual(actions[3][2], (4,))
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=False):
            window.on_run_optimize(None)
            submit.assert_not_called()

    def test_disabling_swap_confirmation_names_the_file_to_be_removed(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": True, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        window.chk_swap.set_active(False)
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window.on_run_optimize(None)
            submit.assert_not_called()
            self.assertIn("/swapfile", confirm.call_args.args[1])
            self.assertIn("permanently removed", confirm.call_args.args[1])

    def test_look_apply_dispatches_rounding_and_explicit_scaling(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_look_settings({"theme": "light", "round": False, "scaling": 1.0})
        window.chk_round.set_active(True)
        window.cmb_scaling.set_active(3)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
        actions = submit.call_args.args[1]
        self.assertEqual([item[0] for item in actions], ["Rounded corners", "Text size"])
        self.assertEqual(actions[0][2], (True,))
        self.assertEqual(actions[1][2], (0.85,))

    def test_optimize_and_look_refreshes_do_not_reset_other_page(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": False, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        window.cmb_theme.set_active(1)
        window.chk_round.set_active(True)
        window._apply_optimize_settings({"animations_off": None, "swap": False,
                                         "zram": False, "power": "balanced"})
        self.assertEqual(window.cmb_theme.get_active_text(), "Dark")
        self.assertTrue(window.chk_round.get_active())
        self.assertFalse(window.chk_animations.get_sensitive())
        self.assertIsNone(window.baseline["animations_off"])
        window.chk_animations.set_active(True)
        with mock.patch.object(window, "submit") as submit:
            window.on_run_optimize(None)
            submit.assert_not_called()

    def test_service_actions_confirm_stop_restart_disable_and_queue_start_enable(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_services([{"unit": "demo.service", "active": "active", "sub": "running",
                                 "description": "Demo", "unit_state": "enabled"}])
        window._on_service_row_selected(window.services_listbox, window.services_listbox.get_children()[0])
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=False) as confirm:
            for action in ("stop", "restart", "disable"):
                window.on_service_action(action)
            self.assertEqual(confirm.call_count, 3)
            submit.assert_not_called()
            for action in ("start", "enable"):
                window.on_service_action(action)
            self.assertEqual(submit.call_count, 2)
            self.assertEqual([c.args[2] for c in submit.call_args_list], ["start", "enable"])

    def test_partial_scans_and_unknown_cleanup_sizes_are_not_reported_as_zero(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._fill_manage_rows(([], ["Flatpak scan failed"]))
        self.assertTrue(window.manage_scan_notice.get_visible())
        self.assertIn("incomplete", window.manage_empty.get_text().lower())
        window._apply_services(None)
        self.assertIn("unavailable", window.services_count.get_text().lower())
        window._on_services_filter_changed()
        self.assertIn("unavailable", window.services_count.get_text().lower())
        window._apply_clean_scan([
            {"key": "journal", "label": "Journal", "detail": "", "size": None, "root": True},
            {"key": "thumbnails", "label": "Thumbnails", "detail": "", "size": 1024, "root": False},
        ])
        self.assertIn("unknown", window.clean_total.get_text())
        self.assertIn("1 size(s) unavailable", window.clean_summary.get_text())
        window.on_clean_select_all()
        self.assertFalse(window.clean_checkbuttons["journal"][0].get_active())
        window.clean_checkbuttons["journal"][0].set_active(True)
        window._update_clean_counter()
        self.assertIn("+ unknown", window.clean_counter.get_text())
        window._after_clean_scan([
            {"key": "journal", "label": "Journal", "detail": "", "size": None, "root": True},
        ], {"journal": None})
        self.assertIn("comparison is unavailable", window.banner_label.get_text())

    def test_simulated_clean_keeps_files_and_reports_preview(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(self.gui.deepclean_backend.USER_CLEAN_PATHS, {"trash": tmp}), \
                mock.patch.object(window, "_confirm", return_value=True):
            target = Path(tmp) / "important.txt"
            target.write_text("keep", encoding="utf-8")
            window._apply_clean_scan([
                {"key": "trash", "label": "Trash", "detail": "", "size": 4, "root": False},
            ])
            window.clean_checkbuttons["trash"][0].set_active(True)
            window.on_clean_selected(None)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            self.assertIn("No files were removed", window.banner_label.get_text())
            self.assertIn("[simulate] would clean", "".join(window.log_buf.lines))

    def test_queued_log_filter_clear_and_append_render_each_line_once(self):
        pending = []
        buffer = FakeTextBuffer()
        log = self.gui.LogBuffer(buffer, Widget())
        with mock.patch.object(self.gui.GLib, "idle_add",
                               side_effect=lambda func, *args: pending.append((func, args))):
            log.append("alpha\n")
            log.set_filter("")
            log.append("beta\n")
            self.assertEqual(len(pending), 1)
            while pending:
                func, args = pending.pop(0)
                func(*args)
            self.assertEqual(buffer.text.count("alpha"), 1)
            self.assertEqual(buffer.text.count("beta"), 1)
            log.set_filter("beta")
            log.append("beta again\n")
            while pending:
                func, args = pending.pop(0)
                func(*args)
            self.assertNotIn("alpha", buffer.text)
            self.assertEqual(buffer.text.count("beta"), 2)
            log.clear()
            log.set_filter("")
            log.append("after clear\n")
            while pending:
                func, args = pending.pop(0)
                func(*args)
            self.assertNotIn("beta", buffer.text)
            self.assertEqual(buffer.text.count("after clear"), 1)

    def test_log_retention_drops_old_lines_from_view_and_saved_history(self):
        buffer = FakeTextBuffer()
        log = self.gui.LogBuffer(buffer, Widget())
        with mock.patch.object(self.gui, "MAX_LOG_LINES", 3):
            log.append("one\ntwo\nthree\n")
            log.append("four\n")
        self.assertEqual(len(log.lines), 3)
        self.assertNotIn("one", buffer.text)
        self.assertIn("four", buffer.text)
        self.assertNotIn("one", "".join(log.lines))

    def test_log_filter_rebuilds_the_view(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window.log_buf.append("[ok] first line\n")
        window.log_buf.append("[failed] second line\n")
        entry = SimpleNamespace(get_text=lambda: "failed")
        window.on_log_filter_changed(entry)
        self.assertEqual(window.log_buf.filter_text, "failed")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "preen.log"
            self.assertTrue(window.log_buf.save(str(destination)))
            saved = destination.read_text(encoding="utf-8")
            self.assertIn("first line", saved)  # filtering affects only the view
            self.assertIn("second line", saved)
        self.assertEqual(window.log_buf._severity("[failed] exit 7"), "error")
        self.assertEqual(window.log_buf._severity("[warning] caution"), "warning")
        entry = SimpleNamespace(get_text=lambda: "")
        window.on_log_filter_changed(entry)
        self.assertEqual(window.log_buf.filter_text, "")
        window.log_buf.clear()
        self.assertEqual(window.log_buf.lines, [])

    def test_handlers_run_without_exceptions(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        # Select two apps, apply a preset, then exercise every page's handlers.
        window.app_rows["vlc"].chk.set_active(True)
        window.app_rows["git"].chk.set_active(True)
        window.cmb_presets.set_active(1)
        window.on_apply_preset(None)
        self.assertTrue(window.app_rows["code"].chk.get_active())

        handlers = [
            window.on_install_selected,
            window.on_update_selected,
            window.on_update_all,
            window.on_uninstall_selected,
            window.on_refresh_status,
            window.on_scan_installed,
            window.on_update_scanned,
            window.on_uninstall_scanned,
            window.on_run_optimize,
            window.on_manage_startup,
            window.on_apply_theme,
            window.on_apply_look,
            window.on_install_icon,
            window.on_snapshot,
            window.on_open_timeshift,
            window.on_export_config,
            window.on_import_config,
            window.on_dashboard_cleanup,
            window._refresh_stats,
            window._refresh_settings,
            window.on_save_log,
            # new UX surfaces
            window.on_select_all,
            window.on_select_none,
            window.on_preferences,
            window.on_help,
            window.on_about,
            window.on_open_logs_page,
            window.on_clear_log,
            window.on_clean_select_all,
            window.on_clean_select_none,
            window.on_refresh_snapshots,
            window.on_refresh_services,
            window._on_services_filter_changed,
            window._update_clean_counter,
        ]
        for handler in handlers:
            with self.subTest(handler=handler.__name__):
                handler(None)
        window.on_toggle_simulate(window.sim_switch, None)
        window.on_toggle_auto_scroll(window.sim_switch, None)
        window._notify("Something needs your attention", "warning")
        window._notify("Nothing selected", "warning")
        window._require_selection()
        window._on_install_search_changed(None)
        window._on_manage_search_changed(None)
        window._fill_manage_rows([
            {"source": "flatpak", "id": "com.spotify.Client", "name": "Spotify", "protected": False},
            {"source": "apt", "id": "gnome-shell", "name": "GNOME Shell", "protected": True},
        ])
        self.assertEqual(len(window.manage_listbox.get_children()), 2)

    def test_segmented_source_control_switches_and_reports(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self.assertEqual(window.install_source.get_active_text(), "Flatpak")
        window.install_source.set_active(1)
        self.assertEqual(window.install_source.get_active_text(), "APT")
        window.install_source.set_active(0)
        self.assertEqual(window._source(), "flatpak")

    def test_deep_clean_counter_tracks_selection(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_clean_scan([
            {"key": "thumbnails", "label": "Thumbnails", "detail": "", "size": 1024, "root": False},
            {"key": "trash", "label": "Trash", "detail": "", "size": 3 * 1024 ** 2, "root": False},
        ])
        self.assertIn("No items selected", window.clean_counter.get_text())
        window.on_clean_select_all(None)
        self.assertIn("2 selected", window.clean_counter.get_text())
        window.on_clean_select_none(None)
        self.assertIn("No items selected", window.clean_counter.get_text())

    def test_sidebar_search_filters_rows_and_hides_headers(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        rows = window.sidebar_list.get_children()

        # An empty query keeps every row and section header visible.
        self.assertTrue(all(window._sidebar_filter(row) for row in rows))

        # A query matches the Deep Clean page and nothing else.
        entry = SimpleNamespace(get_text=lambda: "deep")
        window._on_sidebar_search_changed(entry)
        visible = [row for row in rows if window._sidebar_filter(row)]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].page_name, "deepclean")

        # Section headers disappear while a search is active.
        header = next(row for row in rows
                      if getattr(row, "page_name", None) is None)
        self.assertFalse(window._sidebar_filter(header))

        # Clearing the query restores every row.
        window._on_sidebar_search_changed(SimpleNamespace(get_text=lambda: ""))
        self.assertTrue(all(window._sidebar_filter(row) for row in rows))

    def test_every_swap_size_option_maps_to_its_requested_capacity(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        for index, size in enumerate((1, 2, 4, 8)):
            with self.subTest(size=size):
                window.cmb_swap_size.set_active(index)
                self.assertEqual(window._swap_size(), size)

    def test_swap_size_combo_sensitivity_follows_switch(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window.chk_swap.set_active(False)
        window._on_swap_toggle(None)
        self.assertFalse(window.cmb_swap_size.get_sensitive())
        window.chk_swap.set_active(True)
        window._on_swap_toggle(None)
        self.assertTrue(window.cmb_swap_size.get_sensitive())

    def test_services_filter_and_count(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_services([
            {"unit": "running.service", "load": "loaded", "active": "active",
             "sub": "running", "description": "Running one", "unit_state": "enabled"},
            {"unit": "stopped.service", "load": "loaded", "active": "inactive",
             "sub": "dead", "description": "Stopped one", "unit_state": "disabled"},
        ])
        self.assertEqual(len(window.services_listbox.get_children()), 2)
        window.chk_running_only.set_active(1)
        window._on_services_filter_changed(None)
        visible = [r for r in window.services_listbox.get_children()
                   if window._services_filter(r, None)]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].unit, "running.service")
        self.assertIn("Showing 1 of 2", window.services_count.get_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
