"""Runtime GUI smoke test using a fake GTK.

PyGObject is not available in this environment, so this walks the entire
MainWindow construction path and clicks most handlers with stand-in widgets.
It catches typos, missing attributes and bad call signatures that an
import-only test cannot.
"""
from __future__ import annotations

import importlib
import os
import re
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
    def __init__(self):
        self.classes = set()

    def add_class(self, name):
        self.classes.add(name)

    def remove_class(self, name):
        self.classes.discard(name)

    def add_provider(self, *_args):
        return None


class FakeAccessible:
    def __init__(self):
        self.name = None

    def set_name(self, name):
        self.name = name


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
        self._style = FakeStyleContext()
        self._accessible = FakeAccessible()
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
        return self._style

    def get_accessible(self):
        return self._accessible

    def set_icon_from_file(self, path):
        self.icon_file = path

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
    def new_from_icon_name(cls, name, *_args):
        image = cls()
        image.icon_name = name
        return image

    @classmethod
    def new_from_pixbuf(cls, pixbuf):
        image = cls()
        image.pixbuf = pixbuf
        return image


class FakeIconTheme:
    @staticmethod
    def get_default():
        return SimpleNamespace(has_icon=lambda _name: False)


class FakePixbuf:
    @staticmethod
    def new_from_file_at_scale(path, width, height, preserve_aspect):
        return (path, width, height, preserve_aspect)


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


class FakeTargetEntry:
    @staticmethod
    def new(*_args, **_kwargs):
        return object()


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
    IconTheme = FakeIconTheme
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
    TargetEntry = FakeTargetEntry

    class StyleContext:
        @staticmethod
        def add_provider_for_screen(*_args):
            return None

    DestDefaults = SimpleNamespace(ALL=0)

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
        repo.Gio = SimpleNamespace(
            SettingsSchemaSource=SimpleNamespace(get_default=lambda: None),
            FileMonitorEvent=SimpleNamespace(CREATED=1, RENAMED=2, CHANGED=3),
            File=SimpleNamespace(
                new_for_uri=lambda uri: SimpleNamespace(get_path=lambda: None),
                new_for_path=lambda path: SimpleNamespace(
                    monitor_directory=lambda *args: SimpleNamespace(
                        connect=lambda *args: None)),
            ),
        )
        repo.GdkPixbuf = SimpleNamespace(Pixbuf=FakePixbuf)
        repo.Gdk = SimpleNamespace(
            Screen=SimpleNamespace(get_default=lambda: object()),
            DragAction=SimpleNamespace(COPY=1),
        )
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
        # AppImage scans must hit a sandboxed HOME, never the real one.
        env_patch = mock.patch.dict(os.environ, {
            "HOME": tmp.name,
            "XDG_DATA_HOME": os.path.join(tmp.name, "xdg-data"),
            "XDG_CONFIG_HOME": os.path.join(tmp.name, "xdg-config"),
        })
        env_patch.start()
        self.addCleanup(env_patch.stop)
        # The update check reaches apt/Flatpak/snap — default to "none found"
        # so _fill_manage_rows never touches the real machine in tests.
        updates_patch = mock.patch.object(self.gui.apps_backend, "list_updates",
                                          return_value={})
        updates_patch.start()
        self.addCleanup(updates_patch.stop)

    def test_window_builds_and_all_pages_exist(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self.assertEqual(len(window.stack.get_children()), 10)
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
        self.assertTrue(hasattr(window, "appimage_list"))
        self.assertTrue(hasattr(window, "fm_scripts_switch"))
        self.assertTrue(hasattr(window, "chk_ufw"))
        self.assertTrue(window.icon_file.endswith("assets/preen.png"))
        self.assertTrue((self.gui.ASSETS_DIR / "preen.png").is_file())
        self.assertEqual(window.sim_switch.get_accessible().name, "Simulate")
        self.assertEqual(window.cmb_theme.get_accessible().name, "Preen appearance")
        self.assertEqual(window.app_rows["org.mozilla.firefox"].chk.get_accessible().name, "Select Firefox")
        # Four non-selectable section headers plus ten page rows.
        section_rows = [r for r in window.sidebar_list.get_children()
                        if getattr(r, "page_name", False) is None]
        self.assertEqual(len(section_rows), 4)

    def test_desktop_launcher_matches_application_id_and_retains_hidden_legacy_alias(self):
        root = Path(__file__).resolve().parents[1] / "data"
        canonical = (root / (self.gui.APP_ID + ".desktop")).read_text(encoding="utf-8")
        legacy = (root / "preen.desktop").read_text(encoding="utf-8")
        self.assertIn("Icon=preen\n", canonical)
        self.assertNotIn("NoDisplay=true", canonical)
        self.assertIn("Icon=preen\n", legacy)
        self.assertIn("NoDisplay=true", legacy)

    def test_startup_prioritizes_reading_appearance_before_package_scans(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(window, "submit") as submit:
            window._start_initial_tasks()
        self.assertEqual(submit.call_args_list[0].args[0], window._read_settings)

    def test_dark_and_light_palettes_keep_required_tokens_and_readable_contrast(self):
        def colors(css):
            return dict(re.findall(r"@define-color (preen_\w+) (#[0-9a-f]{6});", css.decode()))

        def contrast(first, second):
            def luminance(value):
                rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
                linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
                          for x in rgb]
                return sum(x * weight for x, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
            low, high = sorted((luminance(first), luminance(second)))
            return (high + 0.05) / (low + 0.05)

        dark = colors(self.gui._CSS)
        light = colors(self.gui._LIGHT_CSS)
        expected = {
            "preen_bg": "#202124", "preen_sidebar": "#1b1c1e", "preen_surface": "#282a2d",
            "preen_elevated": "#303236", "preen_text": "#f1f3f4", "preen_muted": "#a5a9b0",
            "preen_border": "#3b3e42", "preen_accent": "#3584e4", "preen_success": "#57a773",
            "preen_warning": "#e5a84b", "preen_error": "#e45b5b",
        }
        for token, value in expected.items():
            self.assertEqual(dark[token], value)
        for palette in (dark, light):
            for background in ("preen_bg", "preen_sidebar", "preen_surface", "preen_elevated"):
                for foreground in ("preen_text", "preen_muted"):
                    self.assertGreaterEqual(contrast(palette[foreground], palette[background]), 4.5)
            self.assertGreaterEqual(contrast("#ffffff", palette["preen_action"]), 4.5)
            self.assertGreaterEqual(contrast(palette["preen_warning"], palette["preen_elevated"]), 4.5)
            # Switch tracks and their white thumb remain distinguishable on
            # both cards; accent borders distinguish checked controls.
            self.assertGreaterEqual(contrast("#7a8088", palette["preen_elevated"]), 3.0)
            self.assertGreaterEqual(contrast("#ffffff", "#7a8088"), 3.0)
            self.assertGreaterEqual(contrast(palette["preen_accent"], palette["preen_elevated"]), 3.0)
            self.assertGreaterEqual(contrast("#ffffff", palette["preen_accent"]), 3.0)
        self.assertGreaterEqual(contrast("#f08080", dark["preen_elevated"]), 4.5)
        self.assertGreaterEqual(contrast("#a52323", light["preen_elevated"]), 4.5)
        self.assertGreaterEqual(contrast("#70c28a", dark["preen_elevated"]), 4.5)
        self.assertGreaterEqual(contrast("#1d713f", light["preen_elevated"]), 4.5)

    def test_control_indicators_and_missing_symbolic_icons_have_fallbacks(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        for name in ("check", "mixed", "radio"):
            path = self.gui.ASSETS_DIR / "controls" / (name + ".png")
            self.assertTrue(path.is_file())
            self.assertIn(path.as_uri().encode(), self.gui._CSS)
            self.assertIn(path.as_uri().encode(), self.gui._LIGHT_CSS)
        for name, fallback in (("document-save-symbolic", "↓"),
                               ("edit-select-all-symbolic", "✓"),
                               ("object-select-symbolic", "✓")):
            icon = window._icon(name)
            self.assertEqual(icon.get_text(), fallback)
            self.assertIn("control-fallback-icon", icon.get_style_context().classes)
        with mock.patch.object(self.gui.Gtk.IconTheme, "get_default",
                               return_value=SimpleNamespace(has_icon=lambda name: name == "document-save-symbolic")):
            self.assertEqual(window._icon("document-save-symbolic").icon_name, "document-save-symbolic")

    def test_application_icons_prefer_installed_then_offline_then_generic(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        theme = SimpleNamespace(has_icon=lambda name: name == "actual-desktop-icon")
        desktop_icon = SimpleNamespace(get_names=lambda: ["actual-desktop-icon"])
        app_info = SimpleNamespace(get_icon=lambda: desktop_icon)
        desktop_type = SimpleNamespace(new=lambda _id: app_info)
        with mock.patch.object(self.gui.Gtk.IconTheme, "get_default", return_value=theme), \
                mock.patch.object(self.gui.Gio, "DesktopAppInfo", desktop_type, create=True):
            tile = window._app_icon({"id": "demo", "name": "Demo", "icon_asset": "firefox"})
            self.assertEqual(tile.get_children()[0].icon_name, "actual-desktop-icon")
            self.assertNotIn("app-icon-brand", tile.get_style_context().classes)
        item = self.gui.apps_backend.all_apps()["org.mozilla.firefox"]
        tile = window._app_icon(item)
        self.assertIn("app-icon-brand", tile.get_style_context().classes)
        self.assertTrue(tile.get_children()[0].pixbuf[0].endswith("firefox.png"))
        # Absolute Icon= paths from APT desktop files are preferred too.
        installed_path = str(self.gui.ASSETS_DIR / "controls" / "check.png")
        tile = window._app_icon({"id": "demo", "name": "Demo", "icon": installed_path,
                                 "icon_asset": "firefox"})
        self.assertEqual(tile.get_children()[0].pixbuf[0], installed_path)
        self.assertNotIn("app-icon-brand", tile.get_style_context().classes)
        tile = window._app_icon({"id": "unknown", "name": "Unknown App", "icon_asset": "../unsafe"})
        self.assertIn("app-icon-generic", tile.get_style_context().classes)
        self.assertEqual(tile.get_children()[0].get_text(), "UA")
        # Every catalogue row gets a visible child even without a system icon theme.
        for item in self.gui.apps_backend.all_apps().values():
            self.assertEqual(len(window._app_icon(item).get_children()), 1)

    def test_invalid_image_file_falls_back_to_initials(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        with mock.patch.object(self.gui.GdkPixbuf.Pixbuf, "new_from_file_at_scale", side_effect=ValueError("bad image")):
            tile = window._app_icon(self.gui.apps_backend.all_apps()["org.mozilla.firefox"])
        self.assertIn("app-icon-generic", tile.get_style_context().classes)
        self.assertTrue(tile.get_children()[0].get_text())

    def test_manage_scan_matches_catalogue_marks_by_actual_package_reference(self):
        entries = [{"source": "flatpak", "id": "org.mozilla.firefox", "name": "Firefox"},
                   {"source": "apt", "id": "vlc", "name": "VLC"},
                   {"source": "apt", "id": "unknown", "name": "Unknown"}]
        with mock.patch.object(self.gui.apps_backend, "list_installed_flatpak", return_value=entries[:1]), \
                mock.patch.object(self.gui.apps_backend, "list_installed_apt", return_value=entries[1:]), \
                mock.patch.object(self.gui.apps_backend, "list_installed_snap", return_value=[]):
            scanned, warnings = self.gui.MainWindow._scan_installed_worker()
        self.assertEqual(warnings, [])
        self.assertEqual([item.get("icon_asset") for item in scanned], ["firefox", "vlcmediaplayer", None])

    def test_manage_scan_includes_snap_rows_with_badge(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._fill_manage_rows([
            {"source": "snap", "id": "firefox", "name": "firefox", "protected": False},
            {"source": "snap", "id": "core22", "name": "core22", "protected": True},
        ])
        window.on_manage_select_all(None)
        self.assertEqual(len(window._selected_manage()), 1)  # base snap protected
        self.assertEqual(window._selected_manage()[0]["id"], "firefox")

    def test_manage_update_badges_flag_rows_and_update_button_uses_them(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._fill_manage_rows([
            {"source": "flatpak", "id": "com.spotify.Client", "name": "Spotify",
             "protected": False},
            {"source": "apt", "id": "vlc", "name": "VLC", "protected": False},
            {"source": "apt", "id": "gnome-shell", "name": "GNOME Shell", "protected": True},
        ])
        window._apply_manage_updates({"apt": {"vlc", "gnome-shell"},
                                      "flatpak": set(), "snap": set()})
        rows = {row.entry["id"]: row for row in window.manage_listbox.get_children()
                if getattr(row, "entry", None)}
        self.assertEqual(rows["vlc"].status_label.get_text(), "Update available")
        self.assertTrue(rows["vlc"].entry.get("updatable"))
        self.assertEqual(rows["gnome-shell"].status_label.get_text(), "Protected")
        self.assertFalse(rows["gnome-shell"].entry.get("updatable", False))
        self.assertEqual(rows["com.spotify.Client"].status_label.get_text(), "Installed")
        # Update with nothing ticked selects the flagged rows (never protected ones).
        with mock.patch.object(window, "submit") as submit:
            window.on_update_scanned(None)
        self.assertTrue(submit.called)
        picked = submit.call_args[0][1]
        self.assertEqual([entry["id"] for entry in picked], ["vlc"])
        self.assertTrue(rows["vlc"].chk.get_active())

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
        settings_backend.set_value("appearance_mode", "light")
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": False, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window._css_provider.css, self.gui._LIGHT_CSS)
        window.chk_animations.set_active(True)
        window.chk_round.set_active(True)
        window.cmb_scaling.set_active(2)
        window.cmb_theme.set_active(2)
        with mock.patch.object(utils, "_simulate", False), \
                mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="light"):
            window.on_apply_theme(None)
        self.assertEqual(settings_backend.get("appearance_mode"), "dark")
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

    def test_stylesheet_failure_is_reported_without_claiming_a_palette_change(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        previous = window._app_theme
        requested = "light" if previous == "dark" else "dark"
        with mock.patch.object(window._css_provider, "load_from_data", side_effect=ValueError("bad CSS")):
            window._set_app_theme(requested)
        self.assertEqual(window._app_theme, previous)
        self.assertEqual(window._banner_level, "error")
        self.assertIn("bad CSS", "".join(window.log_buf.lines))
        with mock.patch.object(window._css_provider, "load_from_data", return_value=False):
            window._set_app_theme(requested)
        self.assertEqual(window._app_theme, previous)
        self.assertIn("GTK rejected the stylesheet", "".join(window.log_buf.lines))

    def test_saved_appearance_applies_at_start_and_survives_preferences_save(self):
        settings_backend.set_value("appearance_mode", "light")
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"), \
                mock.patch.object(self.gui.LogBuffer, "set_theme") as set_log_theme:
            window = self.gui.MainWindow(self.gui.PreenApp())
        set_log_theme.assert_any_call("light")
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window.cmb_theme.get_active_text(), "Light")

        class AcceptDialog(Widget):
            def run(self):
                return self_gui.Gtk.ResponseType.OK

        self_gui = self.gui
        with mock.patch.object(self.gui.Gtk, "Dialog", AcceptDialog):
            window.on_preferences(None)
        self.assertEqual(settings_backend.get("appearance_mode"), "light")
        self.assertEqual(window.settings["appearance_mode"], "light")

    def test_external_theme_changes_follow_system_but_never_override_explicit_or_staged_choice(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._desktop_theme = "light"
        window._apply_theme_setting("system")
        window.cmb_theme.set_active(2)  # staged, not yet applied
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"):
            window._on_desktop_appearance_changed()
        self.assertEqual(window._app_theme, "dark")
        self.assertEqual(window.baseline["theme"], "system")
        self.assertEqual(window.cmb_theme.get_active_text(), "Dark")
        # Once an explicit mode is saved, desktop signals are ignored.
        window._apply_theme_setting("light")
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"):
            window._on_desktop_appearance_changed()
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window.baseline["theme"], "light")
        self.assertEqual(window.cmb_theme.get_active_text(), "Light")

    def test_simulated_theme_keeps_actual_palette_and_can_be_retried(self):
        settings_backend.set_value("appearance_mode", "light")
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_theme_setting("light")
        window.cmb_theme.set_active(2)
        with mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="dark"):
            window.on_apply_theme(None)
        self.assertEqual(settings_backend.get("appearance_mode"), "light")
        self.assertEqual(window._app_theme, "light")
        self.assertEqual(window.cmb_theme.get_active_text(), "Light")
        self.assertEqual(window.baseline["theme"], "light")
        window.cmb_theme.set_active(2)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual(submit.call_args.args[1][0][0], "Theme")

    def test_custom_and_unreadable_scaling_are_never_silently_overwritten(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        info = {"theme": "light", "round": False, "scaling": 1.23}
        window._apply_look_settings(info)
        self.assertEqual(window.cmb_scaling.get_active_text(), "Custom (123%)")
        window.cmb_theme.set_active(2)
        with mock.patch.object(window, "submit") as submit:
            window.on_apply_look(None)
            self.assertEqual([action[0] for action in submit.call_args.args[1]], ["Theme"])
        window.cmb_scaling.set_active(0)
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=True):
            window.on_apply_look(None)
            self.assertEqual([action[0] for action in submit.call_args.args[1]], ["Theme", "Text size"])
        window._apply_look_settings(dict(info, scaling=None))
        self.assertEqual(window.cmb_scaling.get_active_text(), "Unavailable")
        self.assertFalse(window.cmb_scaling.get_sensitive())
        window.cmb_theme.set_active(2)
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
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=True) as confirm:
            window.on_apply_look(None)
            self.assertIn("other applications", confirm.call_args.args[1])
        actions = submit.call_args.args[1]
        self.assertEqual([item[0] for item in actions], ["Rounded corners", "Text size"])
        self.assertEqual(actions[0][2], (True,))
        self.assertEqual(actions[1][2], (0.85,))

    def test_app_only_look_apply_never_dispatches_desktop_actions(self):
        settings_backend.set_value("appearance_mode", "light")
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_look_settings({"theme": "light", "round": False, "scaling": 1.0})
        window.cmb_theme.set_active(2)
        with mock.patch.object(utils, "_simulate", False), \
                mock.patch.object(window, "_confirm") as confirm, \
                mock.patch.object(self.gui.ui_backend, "get_theme_mode", return_value="light"), \
                mock.patch.object(self.gui.ui_backend, "get_text_scaling", return_value=1.0), \
                mock.patch.object(self.gui.ui_backend, "are_rounded_corners_enabled", return_value=False), \
                mock.patch.object(self.gui.ui_backend, "set_text_scaling") as scaling, \
                mock.patch.object(self.gui.ui_backend, "set_rounded_corners") as corners:
            window.on_apply_look(None)
        self.assertEqual(settings_backend.get("appearance_mode"), "dark")
        self.assertEqual(window._app_theme, "dark")
        confirm.assert_not_called()
        scaling.assert_not_called()
        corners.assert_not_called()

    def test_desktop_wide_look_changes_require_explicit_confirmation(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_look_settings({"theme": "light", "round": False, "scaling": 1.0})
        window.chk_round.set_active(True)
        with mock.patch.object(window, "submit") as submit, \
                mock.patch.object(window, "_confirm", return_value=False) as confirm:
            window.on_apply_look(None)
            confirm.assert_called_once()
            submit.assert_not_called()
        dialog = mock.Mock()
        dialog.run.return_value = self.gui.Gtk.ResponseType.OK
        dialog.get_filename.return_value = "/tmp/icons.tar"
        with mock.patch.object(self.gui.Gtk, "FileChooserDialog", return_value=dialog), \
                mock.patch.object(window, "_confirm", return_value=False) as confirm, \
                mock.patch.object(window, "submit") as submit:
            window.on_install_icon(None)
            self.assertIn("other applications", confirm.call_args.args[1])
            submit.assert_not_called()
        with mock.patch.object(self.gui.Gtk, "FileChooserDialog", return_value=dialog), \
                mock.patch.object(window, "_confirm", return_value=True), \
                mock.patch.object(window, "submit") as submit:
            window.on_install_icon(None)
            self.assertIs(submit.call_args.args[0], self.gui.ui_backend.install_icon_pack)

    def test_optimize_and_look_refreshes_do_not_reset_other_page(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_settings({"animations_off": False, "swap": False, "zram": False,
                                "power": "balanced", "theme": "light", "round": False,
                                "scaling": 1.0, "warnings": []})
        window.cmb_theme.set_active(2)
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
            # new AppImages page
            window.on_rescan_appimages,
            window.on_appimage_install,
            window.on_appimage_uninstall,
            window.on_pick_appimage,
            window.on_set_default_appimage,
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

    def test_manage_select_all_and_clear_honor_search_and_protection(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._fill_manage_rows([
            {"source": "flatpak", "id": "com.spotify.Client", "name": "Spotify", "protected": False},
            {"source": "apt", "id": "gnome-shell", "name": "GNOME Shell", "protected": True},
        ])
        window.on_manage_select_all(None)
        self.assertEqual(len(window._selected_manage()), 1)  # protected row skipped
        window.on_manage_select_none(None)
        self.assertEqual(window._selected_manage(), [])
        window.manage_search.set_text("spotify")
        window.on_manage_select_all(None)
        self.assertEqual(len(window._selected_manage()), 1)
        # Clear only touches the rows the search leaves visible.
        window.manage_search.set_text("gnome")
        window.on_manage_select_none(None)
        self.assertEqual(len(window._selected_manage()), 1)

    def test_install_clear_respects_active_search(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window.on_select_all(None)
        self.assertGreater(len(window._selected_apps()), 5)
        window.install_search.set_text("firefox")
        window.on_select_none(None)
        # Visible rows are cleared; rows hidden by the search keep theirs.
        self.assertFalse(window.app_rows["org.mozilla.firefox"].chk.get_active())
        self.assertTrue(window.app_rows["vlc"].chk.get_active())

    def test_row_activation_toggles_selection(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        row = window.app_rows["vlc"]
        self.assertFalse(row.chk.get_active())
        window._on_install_row_activated(window.install_list, row)
        self.assertTrue(row.chk.get_active())
        window._on_install_row_activated(window.install_list, row)
        self.assertFalse(row.chk.get_active())

    def test_manage_row_activation_toggles_selection(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._fill_manage_rows([
            {"source": "flatpak", "id": "com.spotify.Client", "name": "Spotify", "protected": False},
            {"source": "apt", "id": "gnome-shell", "name": "GNOME Shell", "protected": True},
        ])
        rows = {r.entry["id"]: r for r in window.manage_listbox.get_children()
                if hasattr(r, "entry")}
        window._on_manage_row_activated(window.manage_listbox, rows["com.spotify.Client"])
        self.assertEqual(len(window._selected_manage()), 1)
        # A protected row never toggles from a row click.
        window._on_manage_row_activated(window.manage_listbox, rows["gnome-shell"])
        self.assertEqual(len(window._selected_manage()), 1)

    def test_manage_selection_restore_distinguishes_launchers_of_one_package(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        entries = [
            {"source": "apt", "id": "suite", "name": "Suite",
             "desktop": "suite-main.desktop", "protected": False},
            {"source": "apt", "id": "suite", "name": "Suite Editor",
             "desktop": "suite-editor.desktop", "protected": False},
        ]
        window._fill_manage_rows(entries)
        rows = {r.key[2]: r for r in window.manage_listbox.get_children()
                if getattr(r, "key", None)}
        rows["suite-main.desktop"].chk.set_active(True)
        window._fill_manage_rows(entries)
        rows = {r.key[2]: r for r in window.manage_listbox.get_children()
                if getattr(r, "key", None)}
        self.assertTrue(rows["suite-main.desktop"].chk.get_active())
        self.assertFalse(rows["suite-editor.desktop"].chk.get_active())

    # -- AppImages page ----------------------------------------------------
    def _sandbox_stub(self, name="StubApp-1.2.3-x86_64.AppImage"):
        downloads = Path(os.environ["XDG_DATA_HOME"]).parent / "Downloads"
        downloads.mkdir(exist_ok=True)
        stub = downloads / name
        stub.write_text("#!/bin/sh\n", encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def _installed_entries(self):
        apps = Path(os.environ["XDG_DATA_HOME"]) / "applications"
        return list(apps.glob("preen-appimage-*.desktop"))

    def test_appimages_page_installs_selected_download(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self._sandbox_stub()
        window.on_rescan_appimages()
        downloads = [r for r in window.appimage_list.get_children()
                     if getattr(r, "kind", None) == "download"]
        self.assertEqual(len(downloads), 1)
        downloads[0].chk.set_active(True)
        window._update_appimage_counter()  # the fake emits no toggled signal
        self.assertTrue(window.appimage_buttons["install"].get_sensitive())
        with mock.patch.object(utils, "_simulate", False):
            window.on_appimage_install(None)
        installed = [r for r in window.appimage_list.get_children()
                     if getattr(r, "kind", None) == "installed"]
        self.assertEqual(len(installed), 1)
        self.assertEqual(len(self._installed_entries()), 1)
        self.assertTrue(installed[0].entry.get("managed"))

    def test_appimages_uninstall_removes_selected_install(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        stub = self._sandbox_stub()
        window.on_rescan_appimages()
        [r for r in window.appimage_list.get_children()
         if getattr(r, "kind", None) == "download"][0].chk.set_active(True)
        window._update_appimage_counter()
        with mock.patch.object(utils, "_simulate", False):
            window.on_appimage_install(None)
        installed = [r for r in window.appimage_list.get_children()
                     if getattr(r, "kind", None) == "installed"]
        self.assertEqual(len(installed), 1)
        installed[0].chk.set_active(True)
        window._update_appimage_counter()
        with mock.patch.object(utils, "_simulate", False):
            with mock.patch.object(window, "_confirm", return_value=True):
                window.on_appimage_uninstall(None)
        installed = [r for r in window.appimage_list.get_children()
                     if getattr(r, "kind", None) == "installed"]
        self.assertEqual(installed, [])
        self.assertEqual(self._installed_entries(), [])
        # The download in ~/Downloads survives an uninstall.
        self.assertTrue(stub.exists())

    def test_dropped_appimage_installs_and_unknown_files_are_ignored(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        dropped = Path(os.environ["XDG_DATA_HOME"]).parent / "dropped.AppImage"
        dropped.write_text("#!/bin/sh\n", encoding="utf-8")
        dropped.chmod(0o755)
        with mock.patch.object(utils, "_simulate", False):
            window._handle_dropped_files([str(dropped)])
        self.assertEqual(len(self._installed_entries()), 1)
        # A non-package file is reported and ignored, never installed.
        window._handle_dropped_files(["/tmp/notes.txt"])
        self.assertEqual(len(self._installed_entries()), 1)

    def test_appimage_search_filters_rows(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self._sandbox_stub()
        window.on_rescan_appimages()
        window.appimage_search.set_text("nothing-matches-this")
        window._on_appimage_search_changed(None)
        self.assertTrue(window.appimage_empty.get_visible())
        window.appimage_search.set_text("")
        window._on_appimage_search_changed(None)
        self.assertFalse(window.appimage_empty.get_visible())

    def test_filemanager_scripts_toggle_installs_and_removes(self):
        from preen_tool.backend import appimages as appimages_backend
        window = self.gui.MainWindow(self.gui.PreenApp())
        self.assertFalse(appimages_backend.filemanager_scripts_installed())
        window.fm_scripts_switch.set_active(True)
        with mock.patch.object(utils, "_simulate", False):
            window.on_toggle_fm_scripts(window.fm_scripts_switch, None)
        self.assertTrue(appimages_backend.filemanager_scripts_installed())
        window.fm_scripts_switch.set_active(False)
        with mock.patch.object(utils, "_simulate", False):
            window.on_toggle_fm_scripts(window.fm_scripts_switch, None)
        self.assertFalse(appimages_backend.filemanager_scripts_installed())

    def test_downloads_monitor_notices_new_appimages(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        self.assertFalse(window._downloads_pending)
        file = SimpleNamespace(get_basename=lambda: "Fresh-1.0.AppImage")
        window._on_downloads_changed(None, file, None,
                                     self.gui.Gio.FileMonitorEvent.CREATED)
        self.assertTrue(window._downloads_pending)
        self._sandbox_stub("Fresh-1.0.AppImage")
        window._downloads_settled()
        self.assertFalse(window._downloads_pending)
        rows = [r for r in window.appimage_list.get_children()
                if getattr(r, "kind", None) == "download"]
        self.assertEqual(len(rows), 1)

    def test_ignored_downloads_events_do_not_trigger(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        file = SimpleNamespace(get_basename=lambda: "readme.txt")
        window._on_downloads_changed(None, file, None,
                                     self.gui.Gio.FileMonitorEvent.CREATED)
        self.assertFalse(window._downloads_pending)

    def test_firewall_row_syncs_from_read_settings(self):
        window = self.gui.MainWindow(self.gui.PreenApp())
        window._apply_optimize_settings({
            "animations_off": False, "swap": False, "zram": False,
            "power": None, "ufw": True,
        })
        self.assertTrue(window.chk_ufw.get_active())
        self.assertTrue(window.chk_ufw.get_sensitive())
        window._apply_optimize_settings({
            "animations_off": False, "swap": False, "zram": False,
            "power": None, "ufw": None,
        })
        self.assertFalse(window.chk_ufw.get_sensitive())
        window._apply_optimize_settings({
            "animations_off": False, "swap": False, "zram": False,
            "power": None, "ufw": False,
        })
        self.assertTrue(window.chk_ufw.get_sensitive())
        self.assertFalse(window.chk_ufw.get_active())

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
