"""Single-file dialogs for the file-manager right-click handlers.

Right-clicking an .AppImage and choosing Preen runs ``preen --appimage-handler
FILE``: one small dialog, never the main window. Decisions live in the
backend; long work runs in a thread behind a busy dialog so a 200 MB copy
never looks frozen.
"""
from __future__ import annotations

import os
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .backend import appimages as appimages_backend  # noqa: E402
from .backend import utils  # noqa: E402

_RESP_RUN = 110
_RESP_UPDATE = 120
_RESP_REMOVE = 130


def _notice(title, message, kind=Gtk.MessageType.INFO):
    dialog = Gtk.MessageDialog(flags=0, message_type=kind,
                               buttons=Gtk.ButtonsType.CLOSE, text=title)
    dialog.format_secondary_text(str(message)[:1500])
    dialog.run()
    dialog.destroy()


def _ask(title, message, buttons):
    """(dialog response) for a custom-button question."""
    dialog = Gtk.MessageDialog(flags=0, message_type=Gtk.MessageType.QUESTION,
                               buttons=Gtk.ButtonsType.NONE, text=title)
    dialog.format_secondary_text(str(message)[:1500])
    for label, response in buttons:
        dialog.add_button(label, response)
    response = dialog.run()
    dialog.destroy()
    return response


def _work_dialog(title, work):
    """Run work() in a thread behind a busy dialog and return its Outcome."""
    dialog = Gtk.MessageDialog(flags=0, message_type=Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.NONE, text=title)
    dialog.format_secondary_text("Working…")
    done = threading.Event()
    result = {}

    def target():
        try:
            result["outcome"] = work()
        except Exception as exc:  # a dead worker must not leave a modal stuck
            result["outcome"] = utils.fail("{}: {}".format(type(exc).__name__, exc))
        done.set()
        GLib.idle_add(lambda: dialog.response(Gtk.ResponseType.CLOSE) or False)

    threading.Thread(target=target, daemon=True).start()
    dialog.run()
    dialog.destroy()
    return result.get("outcome") or utils.fail("The operation did not finish.")


def _report(outcome):
    _notice("Preen", outcome.message,
            Gtk.MessageType.INFO if outcome.ok else Gtk.MessageType.ERROR)


def run_appimage_handler(path) -> int:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        _notice("Preen", "File not found: {}".format(path), Gtk.MessageType.ERROR)
        return 1

    installed = appimages_backend.find_installed_for_file(path)
    if installed is None:
        name = appimages_backend.app_name_for_file(path)
        response = _ask(
            "Install {}?".format(name),
            "Preen copies the AppImage into place and adds a menu entry and "
            "icon. The file in Downloads stays where it is.",
            [("_Install", Gtk.ResponseType.OK), ("_Cancel", Gtk.ResponseType.CANCEL)])
        if response != Gtk.ResponseType.OK:
            return 0
        outcome = _work_dialog("Installing {}".format(name),
                               lambda: appimages_backend.install_appimage(path))
        _report(outcome)
        return 0 if outcome.ok else 1

    name = str(installed["name"])
    response = _ask(
        name,
        "This app is installed. Run it, replace the installed copy with this "
        "file, or remove the installed copy.",
        [("Run", _RESP_RUN),
         ("Update from this file", _RESP_UPDATE),
         ("Remove", _RESP_REMOVE),
         ("Cancel", Gtk.ResponseType.CANCEL)])
    if response == _RESP_RUN:
        outcome = appimages_backend.run_appimage(str(installed["path"]))
    elif response == _RESP_UPDATE:
        outcome = _work_dialog("Updating {}".format(name),
                               lambda: appimages_backend.install_appimage(path))
    elif response == _RESP_REMOVE:
        confirm = _ask(
            "Remove {}?".format(name),
            "Deletes the menu entry and Preen's copy of the AppImage. Files "
            "installed outside Preen are kept.",
            [("_Remove", Gtk.ResponseType.OK), ("_Cancel", Gtk.ResponseType.CANCEL)])
        if confirm != Gtk.ResponseType.OK:
            return 0
        outcome = _work_dialog("Removing {}".format(name),
                               lambda: appimages_backend.uninstall_appimage(str(installed["id"])))
    else:
        return 0
    _report(outcome)
    return 0 if outcome.ok else 1


def run_deb_handler(path) -> int:
    path = os.path.abspath(path)
    if not os.path.isfile(path) or not path.lower().endswith(".deb"):
        _notice("Preen", "Not a .deb package: {}".format(path), Gtk.MessageType.ERROR)
        return 1
    response = _ask(
        "Install {}?".format(os.path.basename(path)),
        "Runs apt-get with one polkit password prompt. Dependencies are "
        "resolved by apt.",
        [("_Install", Gtk.ResponseType.OK), ("_Cancel", Gtk.ResponseType.CANCEL)])
    if response != Gtk.ResponseType.OK:
        return 0
    outcome = _work_dialog("Installing {}".format(os.path.basename(path)),
                           lambda: appimages_backend.install_deb(path))
    _report(outcome)
    return 0 if outcome.ok else 1
