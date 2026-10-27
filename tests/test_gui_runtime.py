"""Runtime GUI smoke test using a fake GTK.

PyGObject is not available in this environment, so this walks the entire
MainWindow construction path and clicks most handlers with stand-in widgets.
It catches typos, missing attributes and bad call signatures that an
import-only test cannot.
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zorin_optim_tool.backend import utils  # noqa: E402


class FakeTextBuffer:
    def get_end_iter(self):
        return object()

    def get_start_iter(self):
        return object()

    def get_iter_at_line(self, _line):
        return object()

    def get_line_count(self):
        return 1

    def insert(self, *_args):
        return None

    def delete(self, *_args):
        return None

    def create_mark(self, *_args):
        return object()

    def delete_mark(self, *_args):
        return None

    def set_text(self, *_args):
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

    def remove(self, child):
        if child in self._children:
            self._children.remove(child)

    def get_content_area(self):
        return self

    def get_buffer(self):
        return self._buffer

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


class FakeGtk:
    ApplicationWindow = Widget
    Application = Widget
    Box = Widget
    Button = Widget
    CheckButton = Widget
    ComboBoxText = Widget
    Dialog = Widget
    FileChooserDialog = Widget
    Grid = Widget
    HeaderBar = Widget
    Label = Widget
    ListBox = Widget
    ListBoxRow = Widget
    MessageDialog = Widget
    ScrolledWindow = Widget
    SearchEntry = Widget
    Separator = Widget
    Stack = Widget
    StackSidebar = Widget
    Switch = Widget
    TextView = Widget
    TextBuffer = FakeTextBuffer

    Orientation = SimpleNamespace(HORIZONTAL=0, VERTICAL=1)
    SelectionMode = SimpleNamespace(NONE=0)
    StackTransitionType = SimpleNamespace(CROSSFADE=0)
    MessageType = SimpleNamespace(INFO=0, WARNING=1, ERROR=2)
    ButtonsType = SimpleNamespace(CLOSE=1, OK_CANCEL=2)
    ResponseType = SimpleNamespace(OK=-5, CANCEL=-6, CLOSE=-7, APPLY=-10)
    FileChooserAction = SimpleNamespace(OPEN=0, SAVE=1)
    Justification = SimpleNamespace(LEFT=0)
    WrapMode = SimpleNamespace(WORD_CHAR=2)
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
        repo.Pango = SimpleNamespace(
            EllipsizeMode=SimpleNamespace(END=3))
        gi.repository = repo
        self.patch = mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repo})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        sys.modules.pop("zorin_optim_tool.gui", None)
        self.gui = importlib.import_module("zorin_optim_tool.gui")
        self.addCleanup(lambda: sys.modules.pop("zorin_optim_tool.gui", None))
        self.simulate_patch = mock.patch.object(utils, "_simulate", True)
        self.simulate_patch.start()
        self.addCleanup(self.simulate_patch.stop)
        self.thread_patch = mock.patch.object(self.gui.threading, "Thread", SyncThread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)

    def test_window_builds_and_all_pages_exist(self):
        window = self.gui.MainWindow(self.gui.ZorinOptimizerApp())
        self.assertEqual(len(window.stack.get_children()), 7)
        self.assertIn("code", window.app_rows)
        self.assertTrue(window.log_buf.lines)

    def test_handlers_run_without_exceptions(self):
        window = self.gui.MainWindow(self.gui.ZorinOptimizerApp())
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
        ]
        for handler in handlers:
            with self.subTest(handler=handler.__name__):
                handler(None)
        window.on_toggle_simulate(window.sim_switch, None)
        window._fill_manage_rows([
            {"source": "flatpak", "id": "com.spotify.Client", "name": "Spotify", "protected": False},
            {"source": "apt", "id": "gnome-shell", "name": "GNOME Shell", "protected": True},
        ])
        self.assertEqual(len(window.manage_listbox.get_children()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
