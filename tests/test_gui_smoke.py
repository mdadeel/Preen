"""Import-level smoke tests for the GTK layer.

This sandbox has no PyGObject, so a tiny stub stands in for ``gi.repository``.
It catches syntax errors, bad names in class bodies and broken default
arguments without needing a display server.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _Anything:
    """Stand-in for any GTK enum/constant used in a default argument."""

    def __getattr__(self, _name):
        return _Anything()

    def __call__(self, *_args, **_kwargs):
        return _Anything()


class _Meta(type):
    def __getattr__(cls, _name):
        return _Anything()


class _FakeWidget(metaclass=_Meta):
    pass


class _Namespace:
    """Fake Gtk/GLib/Pango namespace: attribute access yields a class."""

    def __getattr__(self, name):
        return type(name, (_FakeWidget,), {})


class _Repository(types.ModuleType):
    def __getattr__(self, _name):
        return _Namespace()


class _Gi(types.ModuleType):
    def require_version(self, *_args, **_kwargs):
        return None


class GuiImportTest(unittest.TestCase):
    def test_gui_module_imports_and_defines_expected_api(self):
        gi_stub = _Gi("gi")
        repo_stub = _Repository("gi.repository")
        gi_stub.repository = repo_stub
        with mock.patch.dict(sys.modules, {"gi": gi_stub, "gi.repository": repo_stub}):
            sys.modules.pop("zorin_optim_tool.gui", None)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                gui = importlib.import_module("zorin_optim_tool.gui")
            self.assertTrue(hasattr(gui, "MainWindow"))
            self.assertTrue(hasattr(gui, "ZorinOptimizerApp"))
            self.assertTrue(hasattr(gui, "LogBuffer"))
            for name in ("submit", "_finish", "on_install_selected", "on_run_optimize",
                         "on_snapshot", "on_open_timeshift", "on_import_config",
                         "on_toggle_simulate", "_build_dashboard_page"):
                self.assertTrue(hasattr(gui.MainWindow, name), "missing " + name)
        sys.modules.pop("zorin_optim_tool.gui", None)

    def test_launcher_fails_gracefully_without_gtk(self):
        from zorin_optim_tool import app

        stderr = io.StringIO()
        with mock.patch.dict(sys.modules, {"gi": None}):
            with contextlib.redirect_stderr(stderr):
                code = app.main([])
        self.assertEqual(code, 1)
        self.assertIn("python3-gi", stderr.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
