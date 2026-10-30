"""GTK 3 user interface.

Design rules:
* Backend work runs in daemon threads; **every** widget mutation goes through
  ``GLib.idle_add`` (or a ``done=`` callback, which already runs on the UI
  thread). Tasks are serialised so double-clicks cannot spawn five pkexec
  prompts.
* Failures and notices appear in a dismissible banner, not a stack of modal
  dialogs. Only genuinely destructive actions get a confirmation.
* Every page explains what it does in one sentence. No mystery meat buttons.
"""
from __future__ import annotations

import os
import threading
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")  # systems shipping Gdk 4.0 otherwise load it by default and clash with Gtk 3
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .backend import (  # noqa: E402
    appimages as appimages_backend,
    apps as apps_backend,
    backup as backup_backend,
    dashboard as dash_backend,
    deepclean as deepclean_backend,
    drivers as drivers_backend,
    firewall as firewall_backend,
    maintenance as maintenance_backend,
    performance as perf_backend,
    services as services_backend,
    settings as settings_backend,
    system as system_backend,
    ui_customization as ui_backend,
    utils,
)

APP_NAME = "Preen"
APP_ID = "io.github.mdadeel.Preen"
MAX_LOG_LINES = 4000
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# GTK 3 design tokens. Every colour is a named token with a dark and a light
# value, so both palettes are rendered from one source and cannot drift apart.
# Keeping the palette and control states together makes all pages (and native
# GTK dialogs) read as one application. No system theme files are changed.
_TOKENS = {
    "preen_bg": ("#202124", "#f5f6f8"),
    "preen_sidebar": ("#1b1c1e", "#eceff2"),
    "preen_surface": ("#282a2d", "#ffffff"),
    "preen_elevated": ("#303236", "#e8ebef"),
    "preen_text": ("#f1f3f4", "#202124"),
    "preen_muted": ("#a5a9b0", "#58616c"),
    "preen_border": ("#3b3e42", "#ccd2d9"),
    "preen_accent": ("#3584e4", "#3584e4"),
    # White text on the base accent is only 3.77:1. Use a darker action fill.
    "preen_action": ("#2463b5", "#2463b5"),
    "preen_action_hover": ("#1f5faa", "#1f5faa"),
    "preen_success": ("#57a773", "#237a48"),
    "preen_warning": ("#e5a84b", "#8a5200"),
    "preen_error": ("#e45b5b", "#bc3434"),
    "preen_ok_text": ("#70c28a", "#1d713f"),
    "preen_bad_text": ("#f08080", "#a52323"),
    "preen_row_selected": ("#293747", "#dbeafb"),
    "preen_button_hover": ("#3a3d42", "#d9dee5"),
    "preen_button_active": ("#43464b", "#cbd1da"),
    # The white thumb needs a track dark enough for contrast in both modes.
    "preen_switch_track": ("#7a8088", "#7a8088"),
    "preen_scroll": ("#62666c", "#8a929b"),
    "preen_info_banner": ("#263a50", "#e2eefc"),
    "preen_warning_banner": ("#473a26", "#fff2d8"),
    "preen_error_banner": ("#4b2e30", "#fce8e6"),
    "preen_log_info": ("#b8c5d4", "#344054"),
    "preen_log_simulate": ("#7db5f5", "#145db1"),
}

_CSS_TEMPLATE = b"""
@define-color preen_bg __PREEN_BG__;
@define-color preen_sidebar __PREEN_SIDEBAR__;
@define-color preen_surface __PREEN_SURFACE__;
@define-color preen_elevated __PREEN_ELEVATED__;
@define-color preen_text __PREEN_TEXT__;
@define-color preen_muted __PREEN_MUTED__;
@define-color preen_border __PREEN_BORDER__;
@define-color preen_accent __PREEN_ACCENT__;
@define-color preen_action __PREEN_ACTION__;
@define-color preen_action_hover __PREEN_ACTION_HOVER__;
@define-color preen_success __PREEN_SUCCESS__;
@define-color preen_warning __PREEN_WARNING__;
@define-color preen_error __PREEN_ERROR__;
@define-color preen_ok_text __PREEN_OK_TEXT__;
@define-color preen_bad_text __PREEN_BAD_TEXT__;
@define-color preen_row_selected __PREEN_ROW_SELECTED__;
@define-color preen_button_hover __PREEN_BUTTON_HOVER__;
@define-color preen_button_active __PREEN_BUTTON_ACTIVE__;
@define-color preen_switch_track __PREEN_SWITCH_TRACK__;
@define-color preen_scroll __PREEN_SCROLL__;
@define-color preen_info_banner __PREEN_INFO_BANNER__;
@define-color preen_warning_banner __PREEN_WARNING_BANNER__;
@define-color preen_error_banner __PREEN_ERROR_BANNER__;
@define-color preen_log_info __PREEN_LOG_INFO__;
@define-color preen_log_simulate __PREEN_LOG_SIMULATE__;

* { font-family: Cantarell, Inter, Ubuntu, sans-serif; }
window, dialog { background-color: @preen_bg; color: @preen_text; }
label { color: @preen_text; }
headerbar {
    background-image: none;
    background-color: @preen_bg;
    border-bottom: 1px solid @preen_border;
    box-shadow: none;
    min-height: 44px;
    padding: 3px 12px;
}
headerbar .header-title { font-size: 0.95em; font-weight: 600; }
headerbar button.titlebutton {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
    padding: 4px;
}
.header-status { color: @preen_muted; font-size: 0.9em; }
.simulate-banner {
    color: @preen_warning;
    background-color: alpha(@preen_warning, 0.12);
    border: 1px solid alpha(@preen_warning, 0.35);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 0.78em;
    font-weight: 700;
}

.sidebar {
    background-color: @preen_sidebar;
    border-right: 1px solid @preen_border;
    padding: 20px 12px 12px;
}
.sidebar-brand { padding: 0 8px 18px; }
.brand-icon {
    background-color: alpha(@preen_accent, 0.16);
    color: @preen_accent;
    border-radius: 8px;
    min-width: 36px;
    min-height: 36px;
}
.brand-icon image { color: @preen_accent; }
.brand-name { font-size: 1.22em; font-weight: 700; }
.brand-caption { color: @preen_muted; font-size: 0.73em; }
.sidebar .sidebar-search { margin: 0 2px 8px; }
.sidebar list, list { background-color: transparent; }
.sidebar-section {
    color: @preen_muted;
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.05em;
    padding: 13px 10px 5px;
}
.page-row {
    border-left: 3px solid transparent;
    border-radius: 6px;
    padding: 7px 10px;
    margin: 1px 0;
    min-height: 22px;
}
.page-row image { color: @preen_muted; }
.page-row:hover:not(:selected) { background-color: @preen_surface; }
.page-row:selected {
    background-color: @preen_row_selected;
    border-left-color: @preen_accent;
}
.page-row:selected label { color: @preen_text; font-weight: 600; }
.page-row:selected image { color: @preen_accent; }
/* Content lists with single selection (Services) share the sidebar selection. */
row:selected { background-color: @preen_row_selected; }
row:selected label { color: @preen_text; }
row:selected image { color: @preen_accent; }
.sidebar-footer { border-top: 1px solid @preen_border; padding: 12px 4px 0; }
.sidebar-version { color: @preen_muted; font-size: 0.8em; }

.page-title { font-size: 1.65em; font-weight: 700; }
.page-subtitle { color: @preen_muted; font-size: 0.96em; }
.card-title { font-size: 1.06em; font-weight: 700; }
.eyebrow { color: @preen_muted; font-size: 0.75em; font-weight: 700; letter-spacing: 0.05em; }
.hint-label, .dim-label, .counter-label, .settings-sub { color: @preen_muted; font-size: 0.9em; opacity: 1; }
.settings-title { font-weight: 600; }
.card {
    background-color: @preen_surface;
    border: 1px solid @preen_border;
    border-radius: 9px;
    padding: 16px;
}
.settings-row { min-height: 40px; padding: 8px 0; border-bottom: 1px solid @preen_border; }
.settings-row:last-child { border-bottom: none; }

.hero-card {
    background-color: @preen_surface;
    border: 1px solid @preen_border;
    border-radius: 9px;
    padding: 18px 20px;
}
.hero-os { font-size: 1.25em; font-weight: 700; }
.hero-meta { color: @preen_muted; font-size: 0.92em; }
.stat-card {
    background-color: @preen_surface;
    border: 1px solid @preen_border;
    border-radius: 9px;
    padding: 15px;
    min-width: 145px;
}
.stat-card image { color: @preen_muted; }
.stat-name { color: @preen_muted; font-weight: 600; }
.stat-value { font-size: 1.65em; font-weight: 700; }
.stat-detail { color: @preen_muted; font-size: 0.86em; }
progressbar trough {
    background-color: @preen_border;
    border: none;
    border-radius: 4px;
    min-height: 4px;
}
progressbar progress {
    background-color: @preen_accent;
    border: none;
    border-radius: 4px;
    min-height: 4px;
}
.summary-value { font-size: 1.8em; font-weight: 700; }
.summary-caption { color: @preen_muted; font-size: 0.9em; }
.action-list { background-color: @preen_surface; border: 1px solid @preen_border; border-radius: 9px; }
.action-list button { border: none; border-radius: 0; background: transparent; box-shadow: none; padding: 10px 14px; }
.action-list button:hover { background-color: @preen_elevated; }
.action-icon { color: @preen_accent; }
.warning-line { color: @preen_warning; }

.badge, .chip, .chip-muted { color: @preen_muted; font-size: 0.86em; }
.badge-ok, .chip-ok, .status-installed { color: @preen_ok_text; }
.badge-bad, .chip-bad, .status-error { color: @preen_bad_text; }
.status-warning { color: @preen_warning; }
.segmented { background-color: @preen_sidebar; border: 1px solid @preen_border; border-radius: 7px; padding: 2px; }
.segmented button { background: transparent; border: 1px solid transparent; border-radius: 5px; box-shadow: none; padding: 5px 12px; }
.segmented button label { color: @preen_muted; }
.segmented button:checked { background-color: @preen_elevated; color: @preen_text; border-color: @preen_accent; }
.segmented button:checked label { color: @preen_text; font-weight: 700; }

button {
    background-image: none;
    background-color: @preen_elevated;
    color: @preen_text;
    border: 1px solid @preen_border;
    border-radius: 7px;
    box-shadow: none;
    padding: 7px 12px;
}
button:hover { background-color: @preen_button_hover; }
button:active { background-color: @preen_button_active; }
button:disabled { color: @preen_muted; background-color: @preen_surface; border-color: @preen_border; }
button:disabled label, button:disabled image { color: @preen_muted; }
button.suggested-action { background-color: @preen_action; color: #ffffff; border-color: @preen_accent; font-weight: 600; }
button.suggested-action label, button.suggested-action image { color: #ffffff; }
button.suggested-action:hover { background-color: @preen_action_hover; }
button.suggested-action:disabled { background-color: @preen_elevated; color: @preen_muted; border-color: @preen_border; }
button.suggested-action:disabled label, button.suggested-action:disabled image { color: @preen_muted; }
button.destructive-action { color: @preen_bad_text; background-color: @preen_surface; border-color: alpha(@preen_error, 0.55); }
button.destructive-action label, button.destructive-action image { color: @preen_bad_text; }
button.destructive-action:hover { background-color: alpha(@preen_error, 0.17); }
button.destructive-action:disabled { color: @preen_muted; border-color: @preen_border; }
button.destructive-action:disabled label, button.destructive-action:disabled image { color: @preen_muted; }
button.flat { background: transparent; border-color: transparent; box-shadow: none; }
button.flat:hover { background-color: @preen_elevated; }
button:focus, entry:focus, check:focus, switch:focus, row:focus {
    outline-color: @preen_accent;
    outline-style: solid;
    outline-width: 2px;
}
entry {
    background-image: none;
    background-color: @preen_surface;
    color: @preen_text;
    border: 1px solid @preen_border;
    border-radius: 7px;
    padding: 7px 10px;
    box-shadow: none;
}
entry:focus { border-color: @preen_accent; }
entry image { color: @preen_muted; }
check, radio { background-image: none; background-color: @preen_surface; border: 1px solid @preen_muted; border-radius: 4px; min-width: 16px; min-height: 16px; }
check:checked, check:indeterminate, radio:checked { background-color: @preen_action; border-color: @preen_accent; color: #ffffff; }
/* Bundled indicators work even when an icon theme lacks symbolic checkmarks. */
check:checked { -gtk-icon-source: url("__PREEN_CHECK_ICON__"); }
check:indeterminate { -gtk-icon-source: url("__PREEN_MIXED_ICON__"); }
radio { border-radius: 50%; }
radio:checked { -gtk-icon-source: url("__PREEN_RADIO_ICON__"); }
switch { background-image: none; background-color: @preen_switch_track; border: 1px solid @preen_switch_track; border-radius: 999px; min-height: 20px; }
switch:checked { background-color: @preen_accent; border-color: @preen_accent; }
switch slider { background-image: none; background-color: #ffffff; border-radius: 999px; min-width: 18px; min-height: 18px; }
separator { background-color: @preen_border; }
scrollbar { background: transparent; border: none; }
scrollbar slider { background-color: @preen_scroll; border-radius: 8px; min-width: 6px; min-height: 6px; border: none; }
scrollbar trough { background: transparent; border: none; }

.app-row { padding: 9px 12px; border-bottom: 1px solid @preen_border; }
.app-icon-tile { min-width: 32px; min-height: 32px; border-radius: 8px; }
.app-icon-brand { background-color: @preen_action; }
.app-icon-generic { background-color: @preen_elevated; border: 1px solid @preen_border; }
.app-icon-generic label { color: @preen_text; font-weight: 700; font-size: 0.85em; }
.control-fallback-icon { font-weight: 700; }
.app-row:last-child { border-bottom: none; }
.app-row:hover { background-color: alpha(@preen_text, 0.035); }
.list-header { padding: 12px 12px 6px; }
.list-surface { background-color: @preen_surface; border: 1px solid @preen_border; border-radius: 9px; }
.clean-row { padding: 10px 12px; border-bottom: 1px solid @preen_border; }
.action-bar { padding-top: 8px; border-top: 1px solid @preen_border; }
.snapshot-row { padding: 8px 10px; border-bottom: 1px solid @preen_border; }
textview, textview text { background-color: @preen_sidebar; color: @preen_text; }
.log-surface { background-color: @preen_sidebar; border: 1px solid @preen_border; border-radius: 9px; padding: 8px; }
infobar { border-radius: 7px; margin: 8px 24px 0; padding: 3px 8px; }
.info-banner { background-color: @preen_info_banner; }
.warning-banner { background-color: @preen_warning_banner; }
.error-banner { background-color: @preen_error_banner; }
popover, menu { background-color: @preen_elevated; border: 1px solid @preen_border; border-radius: 8px; }
/* Combobox popups are menus; style their items or a light system theme puts
   dark text on this dark surface. */
menuitem { color: @preen_text; min-height: 22px; padding: 5px 10px; }
menuitem:hover { background-color: @preen_row_selected; }
menuitem:disabled, menuitem label:disabled { color: @preen_muted; }
tooltip {
    background-color: @preen_elevated;
    color: @preen_text;
    border: 1px solid @preen_border;
    border-radius: 6px;
    padding: 4px 8px;
}
tooltip label { color: @preen_text; }
dialog > box { padding: 8px; }
"""

def _build_css(mode: str) -> bytes:
    """Render the stylesheet for one palette, with bundled control icons."""
    index = 0 if mode == "dark" else 1
    css = _CSS_TEMPLATE
    for name, values in _TOKENS.items():
        css = css.replace(("__" + name.upper() + "__").encode("ascii"),
                          values[index].encode("ascii"))
    # Resolve indicator assets to absolute file URIs so CSS works from any cwd
    # and when Preen is installed as a wheel, .deb or AppImage.
    for control in ("check", "mixed", "radio"):
        marker = "__PREEN_{}_ICON__".format(control.upper()).encode("ascii")
        css = css.replace(marker, (ASSETS_DIR / "controls" / (control + ".png")).as_uri().encode("ascii"))
    return css


_CSS = _build_css("dark")
_LIGHT_CSS = _build_css("light")


def _log_colors(mode: str) -> dict:
    """Severity colours for the log view, derived from the same tokens."""
    index = 0 if mode == "dark" else 1
    return {
        "info": _TOKENS["preen_log_info"][index],
        "notice": _TOKENS["preen_muted"][index],
        "warning": _TOKENS["preen_warning"][index],
        "error": _TOKENS["preen_error"][index],
        "success": _TOKENS["preen_ok_text"][index],
        "simulate": _TOKENS["preen_log_simulate"][index],
    }


def _escape_markup(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class LogBuffer:
    """Thread-safe diagnostic log, with a filtered, severity-coloured view."""

    def __init__(self, textbuffer: Gtk.TextBuffer, textview: Gtk.TextView):
        self.buf = textbuffer
        self.view = textview
        self.lines = []
        self.auto_scroll = True
        self.filter_text = ""
        self._lock = threading.Lock()
        self._next_sequence = 0
        self._rendered_sequence = -1
        self._render_pending = False
        self._rebuild_requested = False
        create_tag = getattr(self.buf, "create_tag", None)
        self._tags_available = callable(create_tag)
        if self._tags_available:
            for name, color in _log_colors("dark").items():
                create_tag("log-" + name, foreground=color)

    def set_theme(self, mode):
        if self._tags_available:
            table = self.buf.get_tag_table()
            for name, color in _log_colors(mode).items():
                tag = table.lookup("log-" + name)
                if tag is not None:
                    tag.set_property("foreground", color)

    @staticmethod
    def _severity(line):
        lower = line.lower()
        if any(marker in lower for marker in ("[error]", "[failed]", "[timeout]")):
            return "error"
        if "[warning]" in lower or "[warn]" in lower:
            return "warning"
        if "[ok]" in lower or "[success]" in lower:
            return "success"
        if "[simulate]" in lower:
            return "simulate"
        return "notice" if "[notice]" in lower else "info"

    def append(self, text: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        parts = str(text).splitlines(keepends=True)
        lines = ["[{}] {}".format(stamp, part) for part in parts]
        if not lines:
            return
        with self._lock:
            self.lines.extend(lines)
            self._next_sequence += len(lines)
            if len(self.lines) > MAX_LOG_LINES:
                self.lines = self.lines[-MAX_LOG_LINES:]
                self._rebuild_requested = True
            schedule = self._request_render_locked()
        if schedule:
            GLib.idle_add(self._sync_view)

    def _insert(self, line):
        end = self.buf.get_end_iter()
        if self._tags_available:
            self.buf.insert_with_tags_by_name(end, line, "log-" + self._severity(line))
        else:  # also keeps the headless GTK test double useful
            self.buf.insert(end, line)

    def _scroll_to_end(self):
        if self.auto_scroll:
            mark = self.buf.create_mark(None, self.buf.get_end_iter(), True)
            self.view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
            self.buf.delete_mark(mark)

    def _request_render_locked(self):
        if self._render_pending:
            return False
        self._render_pending = True
        return True

    def _sync_view(self):
        # A filter/clear may be queued between two worker appends. Snapshot
        # once and render each sequence number only once, even when the later
        # append happened before this idle callback was dispatched.
        with self._lock:
            lines = list(self.lines)
            first_sequence = self._next_sequence - len(lines)
            last_sequence = self._next_sequence - 1
            query = self.filter_text
            rebuild = self._rebuild_requested
            self._rebuild_requested = False
            self._render_pending = False
        if rebuild:
            self.buf.set_text("")
        for index, line in enumerate(lines):
            if (rebuild or first_sequence + index > self._rendered_sequence) and (
                    not query or query in line.lower()):
                self._insert(line)
        self._rendered_sequence = last_sequence
        self._scroll_to_end()
        return False

    def set_filter(self, text: str):
        """Filter individual lines in the view, not the saved diagnostic log."""
        with self._lock:
            self.filter_text = (text or "").strip().lower()
            self._rebuild_requested = True
            schedule = self._request_render_locked()
        if schedule:
            GLib.idle_add(self._sync_view)

    def clear(self):
        with self._lock:
            self.lines.clear()
            self._rebuild_requested = True
            schedule = self._request_render_locked()
        if schedule:
            GLib.idle_add(self._sync_view)

    def save(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as handle:
                with self._lock:
                    handle.writelines(self.lines)
            return True
        except OSError:
            return False


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=APP_NAME)
        try:
            self.set_icon_from_file(str(ASSETS_DIR / "preen.png"))
        except Exception:
            self.set_icon_name("utilities-system-monitor")
        self.set_default_size(1180, 780)
        self.set_size_request(720, 480)
        window_position = getattr(getattr(Gtk, "WindowPosition", None), "CENTER", None)
        if window_position is not None:
            self.set_position(window_position)
        self._busy = False
        self._busy_lock = threading.Lock()
        self._current_task_name = None
        # FIFO task queue. The old runner rejected every submit() while a
        # task was running, which silently dropped the startup reads (boot
        # info, service list, cleanable scan and preferences never loaded).
        self._queue = deque()
        self.action_widgets = []
        self.app_rows = {}
        self.clean_checkbuttons = {}
        self.selected_service_row = None
        self._downloads_pending = False
        self.baseline = {
            "animations_off": None, "swap": False, "zram": False,
            "power": None, "theme": None, "round": False, "scaling": None,
        }
        self.settings = settings_backend.load()
        self._desktop_theme = None
        if self.settings.get("simulate_on_startup"):
            utils.set_simulate(True)

        self._install_css()

        # Keep the native titlebar and window controls. Page headings live in
        # the content; the small title here provides context while scrolling.
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.header_title = Gtk.Label(label="Dashboard")
        self.header_title.get_style_context().add_class("header-title")
        header.set_custom_title(self.header_title)

        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(label="Working…")
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.get_style_context().add_class("header-status")
        self.busy_box = Gtk.Box(spacing=6)
        self.busy_box.pack_start(self.spinner, False, False, 0)
        self.busy_box.pack_start(self.status_label, False, False, 0)
        self.busy_box.set_no_show_all(True)
        self.busy_box.hide()
        header.pack_start(self.busy_box)
        header.pack_end(self._build_menu_button())

        sim_box = Gtk.Box(spacing=7)
        sim_box.set_valign(Gtk.Align.CENTER)
        sim_box.set_tooltip_text("Preview commands and file changes in Logs without changing the system")
        self.sim_switch = Gtk.Switch()
        self._accessible_name(self.sim_switch, "Simulate")
        self._simulation_forced = os.environ.get(utils.SIMULATE_ENV) == "1"
        self.sim_switch.set_tooltip_text(
            "Simulation is forced by {}".format(utils.SIMULATE_ENV) if self._simulation_forced
            else "Preview actions without making changes. See Logs for details.")
        self.sim_switch.set_active(utils.is_simulate())
        self.sim_switch.set_sensitive(not self._simulation_forced)
        self.sim_switch.connect("notify::active", self.on_toggle_simulate)
        sim_box.pack_start(Gtk.Label(label="Simulate"), False, False, 0)
        sim_box.pack_start(self.sim_switch, False, False, 0)
        header.pack_end(sim_box)
        self.sim_banner = Gtk.Label(label="SIMULATION")
        self.sim_banner.set_tooltip_text("No changes will be made while simulation is enabled")
        self.sim_banner.get_style_context().add_class("simulate-banner")
        self.sim_banner.set_valign(Gtk.Align.CENTER)
        self.sim_banner.set_no_show_all(True)
        header.pack_end(self.sim_banner)
        self.set_titlebar(header)

        self.banner = Gtk.InfoBar()
        self.banner_label = Gtk.Label(label="")
        self.banner_label.set_line_wrap(True)
        self.banner_label.set_xalign(0)
        self.banner.get_content_area().pack_start(self.banner_label, True, True, 0)
        self.banner.add_button("Dismiss", Gtk.ResponseType.CLOSE)
        self.banner.connect("response", self._dismiss_banner)
        self.banner.set_no_show_all(True)
        self.banner.hide()
        self._notification_generation = 0
        self._banner_level = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=120)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.connect("row_selected", self._on_sidebar_row_selected)
        self.sidebar_list.set_filter_func(self._sidebar_filter)
        self._sidebar_query = ""
        self.stack.connect("notify::visible-child-name", self._on_stack_page_changed)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(232, -1)
        sidebar.get_style_context().add_class("sidebar")

        brand = Gtk.Box(spacing=10)
        brand.get_style_context().add_class("sidebar-brand")
        brand_icon = Gtk.Box()
        brand_icon.get_style_context().add_class("brand-icon")
        glyph = self._image_from_file(str(ASSETS_DIR / "preen.png"), 28)
        if glyph is None:
            glyph = self._icon("utilities-system-monitor-symbolic", 20)
        glyph.set_halign(Gtk.Align.CENTER)
        glyph.set_valign(Gtk.Align.CENTER)
        brand_icon.pack_start(glyph, True, True, 0)
        brand.pack_start(brand_icon, False, False, 0)
        brand_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        brand_name = Gtk.Label(label=APP_NAME)
        brand_name.set_xalign(0)
        brand_name.get_style_context().add_class("brand-name")
        brand_caption = Gtk.Label(label="SYSTEM UTILITY")
        brand_caption.set_xalign(0)
        brand_caption.get_style_context().add_class("brand-caption")
        brand_text.pack_start(brand_name, False, False, 0)
        brand_text.pack_start(brand_caption, False, False, 0)
        brand.pack_start(brand_text, True, True, 0)
        sidebar.pack_start(brand, False, False, 0)

        self.sidebar_search = Gtk.SearchEntry()
        self.sidebar_search.set_placeholder_text("Find a page")
        self.sidebar_search.get_style_context().add_class("sidebar-search")
        self.sidebar_search.set_tooltip_text("Search navigation pages")
        self.sidebar_search.connect("search-changed", self._on_sidebar_search_changed)
        sidebar.pack_start(self.sidebar_search, False, False, 0)
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.add(self.sidebar_list)
        sidebar.pack_start(sidebar_scroll, True, True, 0)

        sidebar_footer = Gtk.Box(spacing=8)
        sidebar_footer.get_style_context().add_class("sidebar-footer")
        version = Gtk.Label(label="v" + __version__)
        version.get_style_context().add_class("sidebar-version")
        version.set_xalign(0)
        sidebar_footer.pack_start(version, True, True, 0)
        preferences = Gtk.Button()
        preferences.get_style_context().add_class("flat")
        preferences.set_image(self._icon("preferences-system-symbolic", 16))
        preferences.set_tooltip_text("Preferences")
        preferences.connect("clicked", self.on_preferences)
        sidebar_footer.pack_end(preferences, False, False, 0)
        sidebar.pack_start(sidebar_footer, False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main.pack_start(self.banner, False, False, 0)
        main.pack_start(self.stack, True, True, 0)
        panes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        panes.pack_start(sidebar, False, False, 0)
        panes.pack_start(main, True, True, 0)
        self.add(panes)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.log_view.set_pixels_above_lines(2)
        self.log_view.set_left_margin(8)
        self.log_view.set_right_margin(8)
        self.log_buf = LogBuffer(self.log_view.get_buffer(), self.log_view)
        self.log_buf.set_theme(self._app_theme or "dark")
        if self._style_error:
            self.log_buf.append("[error] Could not load the Preen stylesheet: {}\n".format(self._style_error))
        self._setup_drag_drop()

        # ----- Pages (Dashboard first: it is the landing page) -----
        self._build_dashboard_page()
        self._build_install_page()
        self._build_manage_page()
        self._build_appimages_page()
        self._build_optimize_page()
        self._build_customize_page()
        self._build_deepclean_page()
        self._build_services_page()
        self._build_drivers_page()
        self._build_backup_page()
        self._build_logs_page()
        self._populate_sidebar()
        self._install_accelerators()
        if self._style_error:
            self._notify("Preen's appearance could not be loaded. See Logs for details.",
                         "error", log=False)

        # Saved preferences were applied while building the widgets, so no
        # "changed" signal can start a task before the startup chain does.
        self._update_sim_banner()

        self.show_all()
        self.stack.set_visible_child_name(self.settings.get("page_on_startup", "dashboard"))
        self.log_buf.append("[info] {} {} ready. Simulate is {}.\n".format(
            APP_NAME, __version__, "ON" if utils.is_simulate() else "OFF"))
        self._watch_desktop_appearance()
        self._start_initial_tasks()

    # ------------------------------------------------------------------
    # Small UI factories
    # ------------------------------------------------------------------
    def _install_css(self):
        self._style_error = None
        self._app_theme = None
        self._css_provider = None
        try:
            self._css_provider = Gtk.CssProvider()
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            # Explicit choices can be shown immediately; Follow system uses
            # the dark palette until the asynchronous desktop read completes.
            choice = self.settings.get("appearance_mode", "system")
            self._set_app_theme(choice if choice in ("light", "dark") else "dark")
        except Exception as exc:
            self._style_error = str(exc)

    def _set_app_theme(self, mode):
        """Update GTK settings and the palette in this process only."""
        if mode not in ("light", "dark") or mode == self._app_theme:
            return
        try:
            if self._css_provider is None:
                raise RuntimeError("GTK style provider is unavailable")
            loaded = self._css_provider.load_from_data(_LIGHT_CSS if mode == "light" else _CSS)
            if loaded is False:
                raise RuntimeError("GTK rejected the stylesheet")
            try:
                gtk_settings = Gtk.Settings.get_default()
                if gtk_settings is not None:
                    gtk_settings.set_property("gtk-application-prefer-dark-theme", mode == "dark")
            except (AttributeError, TypeError):
                pass  # GTK test doubles/minimal installations may lack Settings.
        except Exception as exc:
            self._style_error = str(exc)
            log_buf = self.__dict__.get("log_buf")
            if log_buf is not None:
                log_buf.append("[error] Could not update application appearance: {}\n".format(exc))
                self._notify("Preen's appearance could not be updated. See Logs for details.",
                             "error", log=False)
            return
        self._style_error = None
        self._app_theme = mode
        log_buf = self.__dict__.get("log_buf")
        if log_buf is not None:
            log_buf.set_theme(mode)

    def _watch_desktop_appearance(self):
        """Follow external GNOME appearance changes without blocking GTK."""
        self._theme_watch_pending = False
        self._theme_watch_dirty = False
        try:
            source = Gio.SettingsSchemaSource.get_default()
            schema = source.lookup("org.gnome.desktop.interface", True) if source else None
            if schema is None:
                return
            keys = [key for key in ("color-scheme", "gtk-theme") if schema.has_key(key)]
            if keys:
                self._desktop_appearance = Gio.Settings.new_full(schema, None, None)
                for key in keys:
                    self._desktop_appearance.connect("changed::" + key, self._on_desktop_appearance_changed)
        except Exception as exc:
            self.log_buf.append("[warning] Could not monitor desktop appearance: {}\n".format(exc))

    def _on_desktop_appearance_changed(self, *_args):
        if self._theme_watch_pending:
            self._theme_watch_dirty = True
            return
        self._theme_watch_pending = True

        def finished(mode):
            self._theme_watch_pending = False
            if mode in ("light", "dark"):
                self._desktop_theme = mode
                # Follow external changes only when that is the saved app
                # preference. Never overwrite a staged or explicit choice.
                if self.settings.get("appearance_mode", "system") == "system":
                    self._set_app_theme(mode)
            if self._theme_watch_dirty:
                self._theme_watch_dirty = False
                self._on_desktop_appearance_changed()

        self.submit(ui_backend.get_theme_mode, done=finished)

    @staticmethod
    def _accessible_name(widget, text):
        try:
            accessible = widget.get_accessible()
            if accessible is not None:
                accessible.set_name(text)
        except (AttributeError, TypeError):
            pass

    def _header_button(self, label, callback, tooltip):
        button = Gtk.Button()
        inner = Gtk.Box(spacing=6)
        name = "edit-select-all-symbolic" if label == "Select all" else "edit-clear-symbolic"
        inner.pack_start(self._icon(name, 14), False, False, 0)
        inner.pack_start(Gtk.Label(label=label), False, False, 0)
        button.add(inner)
        self._accessible_name(button, label)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", callback)
        return button

    def _build_menu_button(self):
        """One ⋮ button holding Preferences / Help / About, keeping the header compact."""
        popover = Gtk.Popover()
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu.set_border_width(8)

        def add_item(label, icon, callback):
            button = Gtk.Button()
            button.get_style_context().add_class("flat")
            inner = Gtk.Box(spacing=9)
            inner.pack_start(self._icon(icon, 16), False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            button.add(inner)

            def on_click(_btn):
                popover.popdown()
                callback(_btn)

            button.connect("clicked", on_click)
            menu.pack_start(button, False, False, 0)

        add_item("Preferences", "preferences-system-symbolic", self.on_preferences)
        add_item("Help", "help-about-symbolic", self.on_help)
        add_item("About", "dialog-information-symbolic", self.on_about)
        menu.show_all()
        popover.add(menu)

        menu_button = Gtk.MenuButton()
        menu_button.set_image(self._icon("open-menu-symbolic", 16))
        menu_button.set_tooltip_text("Preferences, help and about")
        menu_button.set_popover(popover)
        return menu_button

    _ICON_FALLBACKS = {
        "document-save-symbolic": "↓", "object-select-symbolic": "✓",
        "edit-select-all-symbolic": "✓", "edit-clear-symbolic": "×",
        "view-refresh-symbolic": "⟳", "folder-download-symbolic": "↓",
        "open-menu-symbolic": "⋮", "go-next-symbolic": "›",
        "dialog-warning-symbolic": "!", "dialog-information-symbolic": "i",
        "help-about-symbolic": "?", "list-add-symbolic": "+",
        "user-trash-symbolic": "×", "view-grid-symbolic": "▦",
        "document-open-recent-symbolic": "≡", "text-x-generic-symbolic": "≡",
        "preferences-system-symbolic": "⚙", "preferences-desktop-theme-symbolic": "◐",
        "preferences-desktop-appearance": "◐", "speedometer-symbolic": "◴",
        "system-run-symbolic": "▶", "system-shutdown-symbolic": "⏻",
        "system-software-install-symbolic": "+", "media-memory-symbolic": "▥",
        "drive-harddisk-symbolic": "▣", "drive-multidisk-symbolic": "▣",
        "package-x-generic-symbolic": "▣",
        "utilities-system-monitor-symbolic": "▥", "application-x-executable-symbolic": "◇",
    }

    @classmethod
    def _icon(cls, name, size=16):
        # Check the theme before constructing Gtk.Image: GTK otherwise shows
        # its missing-image glyph instead of raising an exception.
        try:
            theme = Gtk.IconTheme.get_default()
            if theme is not None and theme.has_icon(name):
                icon = Gtk.Image.new_from_icon_name(name, 1)  # Gtk.IconSize.MENU
                icon.set_pixel_size(size)
                return icon
        except Exception:
            pass  # a broken or incomplete icon theme should not break controls
        label = Gtk.Label(label=cls._ICON_FALLBACKS.get(name, "•"))
        label.get_style_context().add_class("control-fallback-icon")
        return label

    def _segmented(self, options, active_index=0, tooltip=None):
        """A compact GTK linked-button source selector.

        Returned box behaves like a ComboBoxText for callers: it exposes
        ``get_active_text()`` and ``set_active(index)``.
        """
        box = Gtk.Box(spacing=0)
        context = box.get_style_context()
        context.add_class("linked")
        context.add_class("segmented")
        if tooltip:
            box.set_tooltip_text(tooltip)
        buttons = []
        state = {"index": active_index, "changing": False}

        def select(index, notify=False):
            if state["changing"] or not 0 <= index < len(buttons):
                return
            changed = state["index"] != index
            state["changing"] = True
            state["index"] = index
            try:
                # Gtk.ToggleButton.set_active() can emit clicked recursively.
                # Guard the entire update, including deselecting the old item.
                for pos, button in enumerate(buttons):
                    if button.get_active() != (pos == index):
                        button.set_active(pos == index)
            finally:
                state["changing"] = False
            callback = getattr(box, "on_changed", None)
            if changed and notify and callable(callback):
                callback()

        for index, text in enumerate(options):
            button = Gtk.ToggleButton(label=text)
            button.set_active(index == active_index)
            button.connect("clicked", lambda _b, i=index: select(i, True))
            buttons.append(button)
            box.pack_start(button, False, False, 0)

        def get_active_text():
            return options[state["index"]]

        box.get_active_text = get_active_text
        box.set_active = select
        box.on_changed = None
        box.buttons = buttons
        box.show_all()
        return box

    @staticmethod
    def _segmented_buttons(box):
        return getattr(box, "buttons", [])

    @staticmethod
    def _chip(text, kind=""):
        chip = Gtk.Label(label=text)
        chip.get_style_context().add_class("chip")
        if kind:
            chip.get_style_context().add_class(kind)
        return chip

    def _button(self, label, callback, tooltip=None, primary=False, destructive=False,
                icon=None, flat=False, lock=True):
        """Build a button. ``lock=False`` marks navigation-only buttons that
        stay clickable while a task runs in the queue."""
        if icon:
            button = Gtk.Button()
            inner = Gtk.Box(spacing=7)
            inner.pack_start(self._icon(icon), False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            button.add(inner)
        else:
            button = Gtk.Button(label=label)
        self._accessible_name(button, label)
        button.connect("clicked", callback)
        if tooltip:
            button.set_tooltip_text(tooltip)
        context = button.get_style_context()
        if primary:
            context.add_class("suggested-action")
        if destructive:
            context.add_class("destructive-action")
        if flat:
            context.add_class("flat")
        button.preen_lock = lock
        self.action_widgets.append(button)
        return button

    def _section(self, title, subtitle=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading = Gtk.Label()
        heading.set_markup("<b>{}</b>".format(_escape_markup(title)))
        heading.set_xalign(0)
        heading.get_style_context().add_class("page-title")
        box.pack_start(heading, False, False, 0)
        if subtitle:
            sub = Gtk.Label(label=subtitle)
            sub.set_xalign(0)
            sub.set_line_wrap(True)
            sub.get_style_context().add_class("page-subtitle")
            box.pack_start(sub, False, False, 0)
        return box

    def _page(self, name, sidebar_title, title, subtitle, icon=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_border_width(24)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        heading = Gtk.Label(label=title)
        heading.set_xalign(0)
        heading.get_style_context().add_class("page-title")
        header.pack_start(heading, False, False, 0)
        sub = Gtk.Label(label=subtitle)
        sub.set_xalign(0)
        sub.set_line_wrap(True)
        sub.get_style_context().add_class("page-subtitle")
        header.pack_start(sub, False, False, 0)
        box.pack_start(header, False, False, 0)
        # Settings/overview pages can grow vertically; list-based pages keep
        # their own expanding scroller and persistent bottom actions.
        if name in ("dashboard", "optimize", "customize", "services", "backup"):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(box)
            self.stack.add_titled(scroll, name, sidebar_title)
        else:
            self.stack.add_titled(box, name, sidebar_title)
        return box

    def _frame(self, label, icon=None, tight=False):
        """A rounded card with a small title row; returns (card, inner_box).

        Tight frames hold connected inset setting rows, so their inner box
        uses no spacing and lets the row hairlines form one grouped list.
        """
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.get_style_context().add_class("card")
        head = Gtk.Box(spacing=8)
        if icon:
            head.pack_start(self._icon(icon), False, False, 0)
        heading = Gtk.Label(label=label)
        heading.set_xalign(0)
        heading.get_style_context().add_class("card-title")
        head.pack_start(heading, False, False, 0)
        card.pack_start(head, False, False, 0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        spacing=0 if tight else 10)
        card.pack_start(inner, True, True, 0)
        return card, inner

    def _toggle_row(self, title, subtitle=None, tooltip=None):
        """A grouped settings row: title (and sub-caption) left, switch right.

        Returns (row_box, switch); callers keep the switch under the same
        attribute name the old check buttons used, so get_active/set_active
        contracts are unchanged.
        """
        row = Gtk.Box(spacing=12)
        row.get_style_context().add_class("settings-row")
        if tooltip:
            row.set_tooltip_text(tooltip)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        title_label.set_line_wrap(True)
        title_label.get_style_context().add_class("settings-title")
        text_box.pack_start(title_label, False, False, 0)
        if subtitle:
            sub_label = Gtk.Label(label=subtitle)
            sub_label.set_xalign(0)
            sub_label.set_line_wrap(True)
            sub_label.get_style_context().add_class("settings-sub")
            text_box.pack_start(sub_label, False, False, 0)
        row.pack_start(text_box, True, True, 0)
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        self._accessible_name(switch, title)
        switch.set_tooltip_text(tooltip or subtitle or title)
        row.pack_end(switch, False, False, 0)
        return row, switch

    def _value_row(self, title, control, subtitle=None):
        """A grouped row with a label left and any control (combo, button) right."""
        row = Gtk.Box(spacing=12)
        row.get_style_context().add_class("settings-row")
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        title_label.get_style_context().add_class("settings-title")
        text_box.pack_start(title_label, False, False, 0)
        if subtitle:
            sub_label = Gtk.Label(label=subtitle)
            sub_label.set_xalign(0)
            sub_label.set_line_wrap(True)
            sub_label.get_style_context().add_class("settings-sub")
            text_box.pack_start(sub_label, False, False, 0)
        row.pack_start(text_box, True, True, 0)
        row.pack_end(control, False, False, 0)
        return row

    @staticmethod
    def _hint(text):
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("dim-label")
        return label

    @staticmethod
    def _counter(text=""):
        label = Gtk.Label(label=text)
        label.set_xalign(1)
        label.set_hexpand(True)
        label.get_style_context().add_class("dim-label")
        return label

    @staticmethod
    def _row(*widgets):
        box = Gtk.Box(spacing=8)
        for widget in widgets:
            box.pack_start(widget, False, False, 0)
        return box

    @staticmethod
    def _flow(*widgets):
        """A compact button row that wraps instead of clipping when resized."""
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(10)
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        flow.set_homogeneous(False)
        for widget in widgets:
            flow.add(widget)
        return flow

    # ------------------------------------------------------------------
    # Keyboard accelerators
    # ------------------------------------------------------------------
    def _install_accelerators(self):
        """Window shortcuts: F5 refresh, Ctrl+F search, Ctrl+A select all,
        Escape dismiss a notice. Guarded because minimal GTK builds and the
        test doubles ship neither Gio.SimpleAction nor accel registration."""
        self._page_refresh_actions = {
            "dashboard": self._refresh_stats, "install": self.on_refresh_status,
            "manage": self.on_scan_installed, "appimages": self.on_rescan_appimages,
            "optimize": self._refresh_optimize_settings,
            "customize": self._refresh_look_settings,
            "deepclean": self.on_scan_cleanable, "services": self.on_refresh_services,
            "drivers": self.on_rescan_drivers, "backup": self.on_refresh_snapshots,
        }
        self._page_find_actions = {
            "install": self.install_search, "manage": self.manage_search,
            "appimages": self.appimage_search, "services": self.services_search,
            "drivers": self.drivers_search, "logs": self.log_filter,
        }
        self._page_select_all_actions = {
            "install": self.on_select_all, "manage": self.on_manage_select_all,
            "deepclean": self.on_clean_select_all,
        }
        simple_action = getattr(Gio, "SimpleAction", None)
        app = self.get_application()
        set_accels = getattr(app, "set_accels_for_action", None) if app is not None else None
        for name, accels, handler in (
            ("refresh-page", ("F5", "<Primary>r"), self._accel_refresh),
            ("find", ("<Primary>f",), self._accel_find),
            ("select-all", ("<Primary>a",), self._accel_select_all),
            ("dismiss-notice", ("Escape",), self._accel_dismiss),
        ):
            if simple_action is not None:
                action = simple_action.new(name, None)
                action.connect("activate", lambda _a, _p, callback=handler: callback())
                self.add_action(action)  # GtkApplicationWindow exposes it as win.<name>
            if callable(set_accels):
                set_accels("win." + name, list(accels))

    def _accel_refresh(self):
        handler = self._page_refresh_actions.get(self.stack.get_visible_child_name())
        if handler is not None:
            handler()

    def _accel_find(self):
        entry = self._page_find_actions.get(self.stack.get_visible_child_name())
        if entry is None:
            entry = self.sidebar_search
        entry.grab_focus()

    def _accel_select_all(self):
        # Inside a text entry, Ctrl+A keeps GTK's native select-text behaviour.
        focus = self.get_focus()
        if focus is not None and isinstance(focus, Gtk.Entry):
            return
        handler = self._page_select_all_actions.get(self.stack.get_visible_child_name())
        if handler is not None:
            handler(None)

    def _accel_dismiss(self):
        if self._banner_level is not None:
            self._dismiss_banner()

    # ------------------------------------------------------------------
    # Sidebar navigation
    # ------------------------------------------------------------------
    # Stable page IDs are shared with preferences and the stack.
    SIDEBAR_SECTIONS = [
        ("Overview", [
            ("dashboard", "Dashboard", "view-grid-symbolic", ""),
        ]),
        ("Software", [
            ("install", "Install Apps", "system-software-install-symbolic", ""),
            ("manage", "Manage Apps", "application-x-executable-symbolic", ""),
            ("appimages", "AppImages", "package-x-generic-symbolic", ""),
        ]),
        ("System", [
            ("deepclean", "Deep Clean", "user-trash-symbolic", ""),
            ("optimize", "Optimize System", "preferences-system-symbolic", ""),
            ("services", "Services", "system-run-symbolic", ""),
            ("drivers", "Drivers", "computer-symbolic", ""),
            ("backup", "Backup & Restore", "document-save-symbolic", ""),
        ]),
        ("Personal", [
            ("customize", "Customize Look", "preferences-desktop-theme-symbolic", ""),
            ("logs", "Logs", "text-x-generic-symbolic", ""),
        ]),
    ]

    def _populate_sidebar(self):
        for section_title, pages in self.SIDEBAR_SECTIONS:
            header_row = Gtk.ListBoxRow()
            header_row.set_activatable(False)
            header_row.set_selectable(False)
            header_row.page_name = None
            header = Gtk.Label(label=section_title.upper())
            header.set_xalign(0)
            header.get_style_context().add_class("sidebar-section")
            header_row.add(header)
            self.sidebar_list.add(header_row)

            for name, label, icon, _unused in pages:
                row = Gtk.ListBoxRow()
                row.page_name = name
                row.search_text = label.lower()
                row.get_style_context().add_class("page-row")
                line = Gtk.Box(spacing=12)
                glyph = self._icon(icon, 16)
                glyph.set_valign(Gtk.Align.CENTER)
                line.pack_start(glyph, False, False, 0)
                text = Gtk.Label(label=label)
                text.set_xalign(0)
                line.pack_start(text, True, True, 0)
                row.add(line)
                self.sidebar_list.add(row)
        self.sidebar_list.show_all()

    def _on_sidebar_row_selected(self, _box, row):
        if row is None:
            return
        name = getattr(row, "page_name", None)
        if name and name != self.stack.get_visible_child_name():
            self.stack.set_visible_child_name(name)

    def _on_sidebar_search_changed(self, entry):
        self._sidebar_query = entry.get_text().strip().lower()
        # Present on the real GTK ListBox; the test double is a no-op here.
        invalidate = getattr(self.sidebar_list, "invalidate_filter", None)
        if callable(invalidate):
            invalidate()

    def _sidebar_filter(self, row):
        if not self._sidebar_query:
            return True
        # Section headers disappear while searching.
        if getattr(row, "page_name", None) is None:
            return False
        return self._sidebar_query in getattr(row, "search_text", "")

    def _on_stack_page_changed(self, _stack, _param):
        name = self.stack.get_visible_child_name()
        if not name:
            return
        for _section, pages in self.SIDEBAR_SECTIONS:
            for page_name, title, _icon, _unused in pages:
                if page_name == name:
                    self.header_title.set_text(title)
                    break
        for row in self.sidebar_list.get_children():
            if getattr(row, "page_name", None) == name:
                self.sidebar_list.select_row(row)
                break

    # ------------------------------------------------------------------
    # Task runner
    # ------------------------------------------------------------------
    def submit(self, func, *args, done=None, name=None):
        """Queue a backend function for a worker thread.

        Tasks run one at a time in FIFO order instead of being rejected while
        another task is running; ``done`` always runs on the UI thread.
        ``name`` is shown in the header while the task runs, so a slow scan
        never reads as a frozen app.
        """
        self._queue.append((func, args, done, name))
        self._pump_queue()
        return True

    def _pump_queue(self):
        with self._busy_lock:
            if self._busy or not self._queue:
                return
            func, args, done, name = self._queue.popleft()
            self._busy = True
            self._current_task_name = name
        # submit() is called on the GTK thread; disable immediately so a
        # double click cannot enqueue a second command before an idle event.
        self._set_busy_ui(True)

        def target():
            try:
                if utils.accepts_log(func):
                    result = func(*args, log=self.log_buf)
                else:
                    result = func(*args)
            except Exception as exc:  # never let a worker die silently
                self.log_buf.append("[error] {}: {}\n{}\n".format(
                    type(exc).__name__, exc, traceback.format_exc()))
                result = utils.fail("{}: {}".format(type(exc).__name__, exc))
            GLib.idle_add(self._finish, result, done)

        threading.Thread(target=target, daemon=True).start()

    def _set_busy_ui(self, busy):
        self.spinner.start() if busy else self.spinner.stop()
        self.status_label.set_text(
            (self._current_task_name or "Working…") if busy else "Ready")
        if busy:
            self.busy_box.set_no_show_all(False)
            self.busy_box.show_all()
        else:
            self.busy_box.hide()
            self.busy_box.set_no_show_all(True)
        # Simulation cannot be switched off halfway through a queued batch.
        self.sim_switch.set_sensitive(not busy and not self._simulation_forced)
        for widget in self.action_widgets:
            # Navigation-only buttons (lock=False) stay usable during tasks:
            # reading the Logs page never conflicts with a queued command.
            if getattr(widget, "preen_lock", True):
                widget.set_sensitive(not busy)
        for button in self._segmented_buttons(self.install_source):
            button.set_sensitive(not busy)
        self._sync_power_control()
        if not busy:
            self._update_install_counter()
            self._update_manage_counter()
            self._update_appimage_counter()
            self._update_clean_counter()
            self._update_service_actions()
            self._sync_ufw_control()
            self._sync_maintenance_control()
            self._on_swap_toggle(None)
            self._update_drivers_counter()
        return False

    def _finish(self, result, done):
        # Remain busy while a completion callback runs: callbacks may enqueue
        # refreshes, and no other worker should race their widget updates.
        if isinstance(result, utils.Outcome):
            message = result.message
            if result.ok and utils.is_simulate() and "simulat" not in message.lower():
                message = "Simulation complete. No changes were made."
            prefix = "[ok] " if result.ok else "[failed] "
            self.log_buf.append(prefix + message + "\n")
            for detail in result.details:
                self.log_buf.append("    - " + detail + "\n")
            if result.ok:
                self._notify(message, "info", log=False)
            else:
                summary = message
                if result.details:
                    summary += ": " + result.details[0][:180]
                self._notify("Action failed: " + summary, "error", log=False)
        if done is not None:
            try:
                done(result)
            except Exception as exc:
                detail = traceback.format_exc()
                self.log_buf.append("[error] UI update failed: {}\n{}\n".format(exc, detail))
                self._notify("The interface could not refresh. See Logs for details.",
                             "error", log=False)
        with self._busy_lock:
            self._busy = False
        if self._queue:
            self._pump_queue()
        else:
            self._set_busy_ui(False)
        return False

    def _start_initial_tasks(self):
        # Read appearance first so a light desktop does not wait behind large
        # package and service scans before Preen adopts the correct palette.
        # The FIFO queue runs the rest one at a time without dropping any.
        self.submit(self._read_settings, done=self._apply_settings, name="Reading preferences")
        self.submit(apps_backend.get_status_label_map, done=self._apply_status,
                    name="Checking app status")
        self.submit(self._scan_installed_worker, done=self._fill_manage_rows,
                    name="Scanning installed apps")
        self.submit(self._scan_appimages_worker, done=self._fill_appimage_rows,
                    name="Scanning AppImages")
        self.submit(dash_backend.get_system_info, done=self._apply_stats,
                    name="Reading system usage")
        self.submit(deepclean_backend.scan_cleanable, done=self._apply_clean_scan,
                    name="Scanning cleanup items")
        self.submit(services_backend.boot_info, done=self._apply_boot,
                    name="Measuring boot time")
        self.submit(services_backend.list_services, done=self._apply_services,
                    name="Listing services")
        self.submit(backup_backend.list_snapshots, done=self._apply_snapshots,
                    name="Listing snapshots")
        self.submit(maintenance_backend.get_schedule, done=self._apply_maintenance_state,
                    name="Reading maintenance schedule")
        self.submit(self._scan_drivers_worker, done=self._fill_drivers_rows,
                    name="Scanning devices")
        interval = self.settings.get("auto_refresh_seconds", 15)
        if interval:
            GLib.timeout_add_seconds(interval, self._periodic_refresh)

    def _periodic_refresh(self):
        with self._busy_lock:
            busy = self._busy
        if not busy:
            self.submit(dash_backend.get_system_info, done=self._apply_stats,
                        name="Reading system usage")
        return True

    # ------------------------------------------------------------------
    # Feedback (non-modal) and dialogs
    # ------------------------------------------------------------------
    def _notify(self, message, level="info", log=True):
        """Show transient notices and dismissible, persistent errors."""
        message = str(message).strip()
        if self._banner_level == "error" and level != "error":
            if log:
                self.log_buf.append("[{}] {}\n".format(level, message))
            return
        self._notification_generation += 1
        self._banner_level = level
        generation = self._notification_generation
        self.banner_label.set_text(message[:600])
        context = self.banner.get_style_context()
        for css_class in ("info-banner", "warning-banner", "error-banner"):
            context.remove_class(css_class)
        context.add_class(level + "-banner")
        self.banner.set_message_type({
            "info": Gtk.MessageType.INFO,
            "warning": Gtk.MessageType.WARNING,
            "error": Gtk.MessageType.ERROR,
        }.get(level, Gtk.MessageType.INFO))
        # The InfoBar starts with no-show-all, so reveal its children too.
        self.banner.get_content_area().show_all()
        self.banner.show_all()
        self.banner_label.show()
        self.banner.show()
        self.banner.set_revealed(True)
        if log:
            self.log_buf.append("[{}] {}\n".format(level, message))
        if level != "error":
            def expire():
                if generation == self._notification_generation:
                    self._dismiss_banner()
                return False
            GLib.timeout_add_seconds(7, expire)

    def _dismiss_banner(self, *_args):
        self._notification_generation += 1
        self._banner_level = None
        self.banner.set_revealed(False)
        self.banner.hide()

    def _notice(self, message):
        self.status_label.set_text(message)
        self.log_buf.append("[notice] " + message + "\n")

    def _show_dialog(self, title, message, kind=Gtk.MessageType.INFO):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=kind,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        if message:
            dialog.format_secondary_text(message[:2000])
        dialog.run()
        dialog.destroy()

    def _confirm(self, title, message, required=True):
        if not required and not self.settings.get("confirm_destructive", True):
            self.log_buf.append("[confirm] skipped (disabled in Preferences)\n")
            return True
        dialog = Gtk.MessageDialog(transient_for=self, flags=0,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=title)
        dialog.format_secondary_text(
            (message[:1200]) + "\n\nTip: turn on Simulate (top right) to preview first.")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _update_sim_banner(self):
        enabled = utils.is_simulate()
        self.sim_banner.set_visible(enabled)
        if enabled:
            self.sim_banner.show()
        else:
            self.sim_banner.hide()

    # ------------------------------------------------------------------
    # Dashboard (landing page)
    # ------------------------------------------------------------------
    def _build_dashboard_page(self):
        page = self._page(
            "dashboard", "Dashboard", "Dashboard",
            "A clear view of your system and the tools available to maintain it.")

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        hero.get_style_context().add_class("hero-card")
        eyebrow = Gtk.Label(label="THIS SYSTEM")
        eyebrow.set_xalign(0)
        eyebrow.get_style_context().add_class("eyebrow")
        self.hero_os = Gtk.Label(label="Reading system information…")
        self.hero_os.set_xalign(0)
        self.hero_os.get_style_context().add_class("hero-os")
        self.lbl_stats = Gtk.Label(label="Collecting system details…")
        self.lbl_stats.set_xalign(0)
        self.lbl_stats.set_line_wrap(True)
        self.lbl_stats.get_style_context().add_class("hero-meta")
        hero.pack_start(eyebrow, False, False, 0)
        hero.pack_start(self.hero_os, False, False, 0)
        hero.pack_start(self.lbl_stats, False, False, 0)
        page.pack_start(hero, False, False, 0)

        resources = Gtk.Box(spacing=8)
        title = Gtk.Label(label="Resource overview")
        title.set_xalign(0)
        title.get_style_context().add_class("card-title")
        resources.pack_start(title, True, True, 0)
        resources.pack_end(self._hint("Live system usage"), False, False, 0)
        page.pack_start(resources, False, False, 0)

        stat_row = Gtk.FlowBox()
        stat_row.set_selection_mode(Gtk.SelectionMode.NONE)
        stat_row.set_min_children_per_line(1)
        stat_row.set_max_children_per_line(4)
        stat_row.set_homogeneous(True)
        stat_row.set_row_spacing(10)
        stat_row.set_column_spacing(10)
        self.stat_bars = {}
        self.stat_details = {}
        for key, name, icon in (("cpu", "CPU", "utilities-system-monitor-symbolic"),
                                ("mem", "Memory", "media-memory-symbolic"),
                                ("disk", "Disk", "drive-harddisk-symbolic"),
                                ("swap", "Swap", "drive-multidisk-symbolic")):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("stat-card")
            head = Gtk.Box(spacing=8)
            head.pack_start(self._icon(icon), False, False, 0)
            name_label = Gtk.Label(label=name)
            name_label.set_xalign(0)
            name_label.get_style_context().add_class("stat-name")
            head.pack_start(name_label, True, True, 0)
            value = Gtk.Label(label="—")
            value.set_xalign(0)
            value.get_style_context().add_class("stat-value")
            detail = Gtk.Label(label="Reading…")
            detail.set_xalign(0)
            detail.set_ellipsize(Pango.EllipsizeMode.END)
            detail.get_style_context().add_class("stat-detail")
            bar = Gtk.ProgressBar()
            bar.set_show_text(False)
            card.pack_start(head, False, False, 0)
            card.pack_start(value, False, False, 0)
            card.pack_start(detail, False, False, 0)
            card.pack_start(bar, False, False, 0)
            stat_row.add(card)
            self.stat_bars[key] = (value, bar)
            self.stat_details[key] = detail
        page.pack_start(stat_row, False, False, 0)

        section = Gtk.Label(label="Suggested next steps")
        section.set_xalign(0)
        section.get_style_context().add_class("card-title")
        page.pack_start(section, False, False, 0)
        action_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        action_list.get_style_context().add_class("action-list")
        for icon, title, detail, target in (
            ("user-trash-symbolic", "Review cleanup opportunities", "See what can be safely cleaned", "deepclean"),
            ("application-x-executable-symbolic", "Manage installed applications", "Review software and protected packages", "manage"),
            ("preferences-system-symbolic", "Optimize system settings", "Review power, memory and desktop settings", "optimize"),
        ):
            button = Gtk.Button()
            button.set_tooltip_text(detail)
            button.connect("clicked", lambda _button, name=target: self.stack.set_visible_child_name(name))
            line = Gtk.Box(spacing=12)
            glyph = self._icon(icon, 18)
            glyph.get_style_context().add_class("action-icon")
            line.pack_start(glyph, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            name_label = Gtk.Label(label=title)
            name_label.set_xalign(0)
            name_label.get_style_context().add_class("settings-title")
            description = self._hint(detail)
            text.pack_start(name_label, False, False, 0)
            text.pack_start(description, False, False, 0)
            line.pack_start(text, True, True, 0)
            line.pack_end(self._icon("go-next-symbolic", 14), False, False, 0)
            button.add(line)
            action_list.pack_start(button, False, False, 0)
        page.pack_start(action_list, False, False, 0)

        # Missing tools are shown in context, not as a permanent empty card.
        self.health_box = Gtk.Box(spacing=10)
        self.health_box.set_no_show_all(True)
        warning_icon = self._icon("dialog-warning-symbolic", 16)
        warning_icon.get_style_context().add_class("warning-line")
        self.health_box.pack_start(warning_icon, False, False, 0)
        health_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.health_chips = Gtk.Box(spacing=6)
        self.lbl_health = Gtk.Label(label="Checking tools…")
        self.lbl_health.set_xalign(0)
        self.lbl_health.set_line_wrap(True)
        self.lbl_health.get_style_context().add_class("hint-label")
        health_text.pack_start(self.health_chips, False, False, 0)
        health_text.pack_start(self.lbl_health, False, False, 0)
        self.health_box.pack_start(health_text, True, True, 0)
        page.pack_start(self.health_box, False, False, 0)

        page.pack_start(self._flow(
            self._button("Refresh Status", self._refresh_stats,
                         "Re-read system information", icon="view-refresh-symbolic"),
            self._button("Run Cleanup", self.on_dashboard_cleanup,
                         "APT autoremove/autoclean and unused Flatpak runtimes"),
            self._button("Open Logs", self.on_open_logs_page,
                         "Review commands and diagnostic messages", lock=False),
        ), False, False, 0)

    def _refresh_stats(self, _btn=None):
        self.submit(dash_backend.get_system_info, done=self._apply_stats,
                    name="Reading system usage")

    def _apply_stats(self, info):
        if not isinstance(info, dict):
            return
        self.hero_os.set_text(str(info.get("os") or "Operating system unavailable"))
        meta = "Kernel {}  ·  Uptime {}  ·  Power {}".format(
            info.get("kernel") or "Unavailable", info.get("uptime") or "Unavailable",
            info.get("power_profile") or "Unavailable")
        if info.get("load_average"):
            meta += "  ·  Load " + str(info["load_average"])
        self.lbl_stats.set_text(meta)
        for key in ("cpu", "mem", "disk", "swap"):
            percent = info.get(key + "_percent")
            try:
                number = float(str(percent).rstrip("%"))
                value = "{}%".format(percent)
                fraction = max(0.0, min(1.0, number / 100.0))
                available = True
            except (TypeError, ValueError):
                value, fraction, available = "—", 0.0, False
            self.stat_bars[key][0].set_text(value)
            self.stat_bars[key][1].set_fraction(fraction)
            self.stat_bars[key][1].set_visible(available)
            if key == "cpu":
                cores = info.get("cpu_cores")
                detail = "{} logical cores".format(cores) if cores and cores != "Unavailable" else "Details unavailable"
            else:
                capacity = info.get(key + "_used")
                detail = "{} used".format(capacity) if capacity and capacity != "Unavailable" else "Capacity unavailable"
            self.stat_details[key].set_text(detail)

    def on_open_logs_page(self, _btn=None):
        self.stack.set_visible_child_name("logs")

    def on_dashboard_cleanup(self, _btn):
        if self._confirm("Run system cleanup?",
                         "Runs apt autoremove/autoclean and removes unused Flatpak runtimes."):
            self.submit(system_backend.run_cleanup, name="Running system cleanup")

    # ------------------------------------------------------------------
    # Install page
    # ------------------------------------------------------------------
    def _build_install_page(self):
        page = self._page(
            "install", "Install Apps", "Install Apps",
            "Discover software and install it from your preferred source. "
            "When a catalogue entry has no package there, Preen uses the other source.")

        toolbar = Gtk.Box(spacing=10)
        self.install_search = Gtk.SearchEntry()
        self.install_search.set_placeholder_text("Search applications")
        self.install_search.set_hexpand(True)
        self.install_search.connect("search-changed", self._on_install_search_changed)
        toolbar.pack_start(self.install_search, True, True, 0)
        source_label = Gtk.Label(label="Source")
        source_label.get_style_context().add_class("dim-label")
        toolbar.pack_start(source_label, False, False, 0)
        self.install_source = self._segmented(
            ("Flatpak", "APT"),
            active_index=1 if self.settings.get("default_source") == "apt" else 0,
            tooltip="The other source is used when the preferred package is not in the catalogue")
        self.install_source.on_changed = self._on_source_changed
        toolbar.pack_start(self.install_source, False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        list_tools = Gtk.Box(spacing=8)
        catalog_label = Gtk.Label(label="APPLICATION CATALOG")
        catalog_label.set_xalign(0)
        catalog_label.get_style_context().add_class("eyebrow")
        list_tools.pack_start(catalog_label, True, True, 0)
        list_tools.pack_end(self._header_button("Clear", self.on_select_none,
                                                 "Clear the visible selection (everything when not searching)"), False, False, 0)
        list_tools.pack_end(self._header_button("Select all", self.on_select_all,
                                                 "Select every app matching the search"), False, False, 0)
        page.pack_start(list_tools, False, False, 0)

        self.install_empty = self._hint("No applications match your search. Try a different term.")
        self.install_empty.set_no_show_all(True)
        self.install_empty.hide()
        self.install_list = Gtk.ListBox()
        self.install_list.set_selection_mode(Gtk.SelectionMode.NONE)
        # Clicking anywhere on a row toggles it — previously only the small
        # checkbox reacted, which read as "selection is broken".
        self.install_list.set_activate_on_single_click(True)
        self.install_list.connect("row-activated", self._on_install_row_activated)
        self.install_list.set_filter_func(self._install_filter, None)
        for category, items in apps_backend.load_apps().items():
            header_row = Gtk.ListBoxRow()
            header_row.set_activatable(False)
            header_row.set_selectable(False)
            header_row.is_header = True
            header_row.get_style_context().add_class("list-header")
            header_label = Gtk.Label(label=category)
            header_label.set_xalign(0)
            header_label.get_style_context().add_class("settings-title")
            header_row.add(header_label)
            self.install_list.add(header_row)
            for item in items:
                app_id = item["id"]
                row = Gtk.ListBoxRow()
                row.set_activatable(True)
                row.is_header = False
                row.app_id = app_id
                row.item = item
                row.status_kind = "checking"
                row.get_style_context().add_class("app-row")
                row.search_text = (item["name"] + " " + category + " " + app_id + " " + item.get("note", "")).lower()
                line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                chk = Gtk.CheckButton()
                chk.set_tooltip_text("Select " + item["name"])
                self._accessible_name(chk, "Select " + item["name"])
                chk.connect("toggled", lambda _c: self._update_install_counter())
                line.pack_start(chk, False, False, 0)
                line.pack_start(self._app_icon(item), False, False, 0)
                text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                name = Gtk.Label(label=item["name"])
                name.set_xalign(0)
                name.set_ellipsize(Pango.EllipsizeMode.END)
                name.get_style_context().add_class("settings-title")
                text.pack_start(name, False, False, 0)
                if item.get("note"):
                    description = Gtk.Label(label=item["note"])
                    description.set_xalign(0)
                    description.set_ellipsize(Pango.EllipsizeMode.END)
                    description.set_tooltip_text(item["note"])
                    description.get_style_context().add_class("settings-sub")
                    text.pack_start(description, False, False, 0)
                line.pack_start(text, True, True, 0)
                source = Gtk.Label(label=self._source_badge(item))
                source.get_style_context().add_class("badge")
                source.set_tooltip_text("Sources listed in the catalogue")
                status = Gtk.Label(label="Checking…")
                status.set_width_chars(12)
                status.set_xalign(1)
                status.get_style_context().add_class("dim-label")
                line.pack_start(source, False, False, 0)
                line.pack_start(status, False, False, 0)
                row.add(line)
                row.chk = chk
                row.status_label = status
                self.app_rows[app_id] = row
                self.install_list.add(row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("list-surface")
        scroller.add(self.install_list)
        page.pack_start(self.install_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.install_counter = self._counter("No apps selected")
        self.install_counter.set_xalign(0)
        preset_row = Gtk.Box(spacing=8)
        preset_row.pack_start(self.install_counter, True, True, 0)
        self.cmb_presets = Gtk.ComboBoxText()
        self.cmb_presets.append_text("Quick picks…")
        self.presets = apps_backend.load_presets()
        for name in self.presets:
            self.cmb_presets.append_text(name)
        self.cmb_presets.set_active(0)
        self.cmb_presets.set_tooltip_text("Choose a curated app preset")
        preset_row.pack_start(self.cmb_presets, False, False, 0)
        preset_row.pack_start(self._button("Apply", self.on_apply_preset,
                                           "Select apps in the chosen preset"), False, False, 0)
        page.pack_start(preset_row, False, False, 0)

        self.install_buttons = {
            "install": self._button("Install Selected", self.on_install_selected,
                                    "Install the selected apps", primary=True),
            "update": self._button("Update Selected", self.on_update_selected,
                                   "Update the selected installed apps"),
            "update_all": self._button("Update All", self.on_update_all,
                                       "Update every package from the preferred source"),
            "uninstall": self._button("Uninstall Selected", self.on_uninstall_selected,
                                      "Uninstall the selected installed apps", destructive=True),
            "refresh": self._button("Refresh Status", self.on_refresh_status,
                                    "Re-check which apps are installed"),
        }
        actions = self._flow(*self.install_buttons.values())
        actions.get_style_context().add_class("action-bar")
        page.pack_start(actions, False, False, 0)
        self._update_install_counter()

    @staticmethod
    def _image_from_file(path, size=22):
        """Load a scaled local icon without allowing a missing/corrupt file to break a row."""
        if not isinstance(path, str) or not os.path.isabs(path) or not os.path.isfile(path):
            return None
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
            return Gtk.Image.new_from_pixbuf(pixbuf)
        except Exception:
            return None

    def _app_icon(self, item):
        """Prefer installed app icons, then a licensed offline mark or generic initials."""
        tile = Gtk.Box()
        tile.set_size_request(32, 32)
        tile.get_style_context().add_class("app-icon-tile")
        try:
            theme = Gtk.IconTheme.get_default()
        except Exception:
            theme = None

        def image_for(value):
            if not isinstance(value, str) or not value:
                return None
            if os.path.isabs(value):
                return self._image_from_file(value)
            try:
                if theme is not None and theme.has_icon(value):
                    image = Gtk.Image.new_from_icon_name(value, 1)
                    image.set_pixel_size(22)
                    return image
            except Exception:
                pass  # fall through to a bundled or generic icon
            return None

        # APT desktop entries can specify an absolute icon or a themed name.
        image = image_for(item.get("icon"))
        candidates = []
        for value in (item.get("flatpak"), item.get("id"), item.get("apt")):
            candidates.extend(apps_backend.as_list(value))

        # The desktop file can name an icon that differs from its package ID.
        # Resolve GIcon names/files without creating an image-missing widget.
        desktop_type = getattr(Gio, "DesktopAppInfo", None)
        if image is None and desktop_type is not None:
            for candidate in candidates:
                try:
                    info = desktop_type.new(candidate + ".desktop")
                    gicon = info.get_icon() if info else None
                    names = gicon.get_names() if gicon and hasattr(gicon, "get_names") else []
                    for name in names or []:
                        image = image_for(name)
                        if image is not None:
                            break
                    if image is None and gicon and hasattr(gicon, "get_file"):
                        file = gicon.get_file()
                        image = image_for(file.get_path() if file else None)
                except Exception:
                    continue  # malformed/missing desktop entries are optional
                if image is not None:
                    break
        if image is None:
            for candidate in candidates:
                image = image_for(candidate)
                if image is not None:
                    break

        if image is None:
            slug = item.get("icon_asset")
            if isinstance(slug, str) and slug.isascii() and slug.isalnum() and slug == slug.lower():
                image = self._image_from_file(str(ASSETS_DIR / "brand" / (slug + ".png")))
                if image is not None:
                    tile.get_style_context().add_class("app-icon-brand")
        if image is None:
            # Do not invent a branded logo for apps without an available mark.
            words = [word for word in str(item.get("name") or item.get("id") or "?").split()
                     if any(char.isalnum() for char in word)]
            initials = "".join(next((c for c in word if c.isalnum()), "") for word in words[:2])
            if len(initials) < 2 and words:
                initials = "".join(c for c in words[0] if c.isalnum())[:2]
            image = Gtk.Label(label=initials.upper() or "?")
            tile.get_style_context().add_class("app-icon-generic")
        image.set_halign(Gtk.Align.CENTER)
        image.set_valign(Gtk.Align.CENTER)
        tile.pack_start(image, True, True, 0)
        return tile

    @staticmethod
    def _source_badge(item):
        has_flat, has_apt = bool(item.get("flatpak")), bool(item.get("apt"))
        if has_flat and has_apt:
            return "Flatpak · APT"
        return "Flatpak" if has_flat else "APT"

    def _install_query(self):
        return self.install_search.get_text().strip().lower()

    def _install_filter(self, row, _data):
        query = self._install_query()
        if getattr(row, "is_header", False):
            return not query
        return not query or query in getattr(row, "search_text", "")

    def _on_install_search_changed(self, _entry):
        self.install_list.invalidate_filter()
        visible = any(self._install_filter(row, None)
                      for row in self.install_list.get_children()
                      if not getattr(row, "is_header", False))
        self.install_empty.set_visible(not visible)
        if not visible:
            self.install_empty.show()
        else:
            self.install_empty.hide()

    def _on_source_changed(self):
        self._update_install_counter()
        self.on_refresh_status(None)

    def _update_install_counter(self):
        selected = self._selected_apps()
        count = len(selected)
        self.install_counter.set_text("{} selected".format(count) if count else "No apps selected")
        if not hasattr(self, "install_buttons"):
            return
        enabled = not self._busy
        # A failed/partial scan is unknown, not proof that nothing is installed.
        can_manage = any(self.app_rows[app_id].status_kind != "not installed"
                         for app_id in selected)
        self.install_buttons["install"].set_sensitive(enabled and count > 0)
        self.install_buttons["update"].set_sensitive(enabled and can_manage)
        self.install_buttons["uninstall"].set_sensitive(enabled and can_manage)
        self.install_buttons["update_all"].set_sensitive(enabled)
        self.install_buttons["refresh"].set_sensitive(enabled)

    def _source(self):
        return (self.install_source.get_active_text() or "Flatpak").lower()

    def _swap_size(self):
        text = self.cmb_swap_size.get_active_text() or "2 GB"
        try:
            return int(text.split()[0])
        except (IndexError, ValueError):
            return 2

    def _selected_apps(self):
        return [app_id for app_id, row in self.app_rows.items() if row.chk.get_active()]

    def _on_install_row_activated(self, _listbox, row):
        chk = getattr(row, "chk", None)
        if chk is not None:
            chk.set_active(not chk.get_active())
            self._update_install_counter()

    def on_select_all(self, _btn):
        query = self._install_query()
        for row in self.app_rows.values():
            if not query or query in row.search_text:
                row.chk.set_active(True)
        self._update_install_counter()

    def on_select_none(self, _btn):
        # Mirror of Select all: with a search active, only visible rows are
        # cleared, so the two buttons can never disagree about their scope.
        query = self._install_query()
        for row in self.app_rows.values():
            if not query or query in row.search_text:
                row.chk.set_active(False)
        self._update_install_counter()

    def on_refresh_status(self, _btn=None):
        apps_backend.invalidate_state()
        self.submit(apps_backend.get_status_label_map, done=self._apply_status,
                    name="Checking app status")

    def _apply_status(self, result):
        if not isinstance(result, dict):
            return
        for app_id, row in self.app_rows.items():
            label = result.get(app_id, "Unavailable")
            kind = label.lower()
            if kind.startswith("installed"):
                display, css_class, row.status_kind = "Installed", "status-installed", "installed"
            elif kind.startswith("update available"):
                display, css_class, row.status_kind = "Update available", "status-warning", "update available"
            elif kind.startswith("not installed"):
                display, css_class, row.status_kind = "Not installed", "dim-label", "not installed"
            elif kind.startswith("error"):
                display, css_class, row.status_kind = "Error", "status-error", "error"
            else:
                display, css_class, row.status_kind = "Unavailable", "status-warning", "unavailable"
            row.status_label.set_text(display)
            row.status_label.set_tooltip_text(label)
            context = row.status_label.get_style_context()
            for old in ("dim-label", "status-installed", "status-warning", "status-error"):
                context.remove_class(old)
            context.add_class(css_class)
        self._update_install_counter()

    def on_apply_preset(self, _btn):
        name = self.cmb_presets.get_active_text()
        app_ids = self.presets.get(name, [])
        if not app_ids:
            self._notify("Choose a preset from the list first.", "warning")
            return
        for app_id, row in self.app_rows.items():
            row.chk.set_active(app_id in app_ids)
        self._update_install_counter()
        self._notice("Preset '{}' selected {} app(s).".format(name, len(app_ids)))

    def _require_selection(self):
        app_ids = self._selected_apps()
        if not app_ids:
            self._notify("Tick at least one app first.", "warning")
            return None
        return app_ids

    def on_install_selected(self, _btn):
        app_ids = self._require_selection()
        if app_ids:
            self.submit(apps_backend.install_apps, app_ids, self._source(),
                        done=lambda _r: self.on_refresh_status(), name="Installing apps")

    def on_update_selected(self, _btn):
        app_ids = self._require_selection()
        if app_ids:
            self.submit(apps_backend.update_apps, app_ids, self._source(),
                        done=lambda _r: self.on_refresh_status(), name="Updating apps")

    def on_uninstall_selected(self, _btn):
        app_ids = self._require_selection()
        if not app_ids:
            return
        if not self._confirm("Uninstall {} app(s)?".format(len(app_ids)),
                             "Removes the installed APT/Flatpak packages for the selected apps."):
            return
        self.submit(apps_backend.uninstall_apps, app_ids, self._source(),
                    done=lambda _r: self.on_refresh_status(), name="Uninstalling apps")

    def on_update_all(self, _btn):
        source = self._source()
        if not self._confirm("Update all {} packages?".format(source.upper()),
                             "Runs a full {} update and may take several minutes.".format(source),
                             required=False):
            return
        self.submit(apps_backend.update_all, source,
                    done=lambda _r: self.on_refresh_status(), name="Updating all packages")

    # ------------------------------------------------------------------
    # Manage page
    # ------------------------------------------------------------------
    def _build_manage_page(self):
        page = self._page(
            "manage", "Manage Apps", "Manage Apps",
            "Review installed Flatpak, Snap and graphical APT applications. "
            "Essential desktop packages are protected from removal.")

        toolbar = Gtk.Box(spacing=8)
        self.manage_search = Gtk.SearchEntry()
        self.manage_search.set_placeholder_text("Search installed applications")
        self.manage_search.set_hexpand(True)
        self.manage_search.connect("search-changed", self._on_manage_search_changed)
        toolbar.pack_start(self.manage_search, True, True, 0)
        toolbar.pack_start(self._button("Scan Installed", self.on_scan_installed,
                                        "Re-scan Flatpak, Snap and graphical APT applications",
                                        icon="view-refresh-symbolic"), False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        list_tools = Gtk.Box(spacing=8)
        manage_label = Gtk.Label(label="INSTALLED APPLICATIONS")
        manage_label.set_xalign(0)
        manage_label.get_style_context().add_class("eyebrow")
        list_tools.pack_start(manage_label, True, True, 0)
        list_tools.pack_end(self._header_button("Clear", self.on_manage_select_none,
                                                "Clear the visible selection (everything when not searching)"),
                             False, False, 0)
        list_tools.pack_end(self._header_button("Select all", self.on_manage_select_all,
                                                "Select every visible installed app (protected packages are skipped)"),
                             False, False, 0)
        page.pack_start(list_tools, False, False, 0)

        self._manage_scan_warnings = []
        self.manage_scan_notice = self._hint("")
        self.manage_scan_notice.get_style_context().add_class("status-warning")
        self.manage_scan_notice.set_no_show_all(True)
        self.manage_scan_notice.hide()
        page.pack_start(self.manage_scan_notice, False, False, 0)

        self.manage_empty = self._hint("No installed applications found. Scan again to refresh the list.")
        self.manage_empty.set_no_show_all(True)
        self.manage_empty.hide()
        self.manage_listbox = Gtk.ListBox()
        self.manage_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.manage_listbox.set_activate_on_single_click(True)
        self.manage_listbox.connect("row-activated", self._on_manage_row_activated)
        self.manage_listbox.set_filter_func(self._manage_filter, None)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("list-surface")
        scroller.add(self.manage_listbox)
        page.pack_start(self.manage_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.manage_counter = self._counter("Nothing selected")
        self.manage_counter.set_xalign(0)
        page.pack_start(self.manage_counter, False, False, 0)
        self.manage_buttons = {
            "update": self._button("Update Selected", self.on_update_scanned,
                                   "Update the selected installed apps", primary=True),
            "uninstall": self._button("Uninstall Selected", self.on_uninstall_scanned,
                                      "Remove the selected installed apps", destructive=True),
        }
        actions = self._flow(*self.manage_buttons.values())
        actions.get_style_context().add_class("action-bar")
        page.pack_start(actions, False, False, 0)
        page.pack_start(self._hint(
            "Protected packages are essential to the desktop and cannot be selected for removal."),
            False, False, 0)
        self._update_manage_counter()

    @staticmethod
    def _scan_installed_worker(log=None):
        warnings = []
        entries = (apps_backend.list_installed_flatpak(warnings, log) +
                   apps_backend.list_installed_apt(warnings, log) +
                   apps_backend.list_installed_snap(warnings, log))
        marks = {}
        for item in apps_backend.all_apps().values():
            if item.get("icon_asset"):
                for source in ("flatpak", "apt"):
                    for ref in apps_backend.as_list(item.get(source)):
                        marks[(source, ref)] = item["icon_asset"]
        for entry in entries:
            asset = marks.get((entry.get("source"), entry.get("id")))
            if asset:
                entry["icon_asset"] = asset
        return entries, warnings

    def _manage_filter(self, row, _data):
        query = self.manage_search.get_text().strip().lower()
        if not hasattr(row, "search_text"):
            return True
        return not query or query in row.search_text

    def _on_manage_search_changed(self, _entry):
        self.manage_listbox.invalidate_filter()
        query = self.manage_search.get_text().strip()
        visible = any(self._manage_filter(row, None)
                      for row in self.manage_listbox.get_children())
        self.manage_empty.set_visible(not visible)
        if not visible:
            self.manage_empty.set_text(
                "No apps match your search. Clear the search box to see them all."
                if query else
                "Scan incomplete; installed applications may be missing. See Logs."
                if self._manage_scan_warnings else
                "No installed applications found. Scan again to refresh the list.")
            self.manage_empty.show()
        else:
            self.manage_empty.hide()

    def on_scan_installed(self, _btn=None):
        self.submit(self._scan_installed_worker, done=self._fill_manage_rows,
                    name="Scanning installed apps")

    def _update_manage_counter(self):
        count = len(self._selected_manage())
        self.manage_counter.set_text("{} selected".format(count) if count else "Nothing selected")
        if hasattr(self, "manage_buttons"):
            for button in self.manage_buttons.values():
                button.set_sensitive(not self._busy and count > 0)

    def _fill_manage_rows(self, result):
        if isinstance(result, tuple) and len(result) == 2:
            entries, warnings = result
        else:
            entries, warnings = result, []
        if not isinstance(entries, list):
            return
        self._manage_scan_warnings = warnings
        if warnings:
            self.manage_scan_notice.set_text("Some sources could not be scanned. See Logs for details.")
            self.manage_scan_notice.set_tooltip_text("\n".join(warnings))
            self.manage_scan_notice.show()
        else:
            self.manage_scan_notice.hide()
        previously_selected = {
            row.key
            for row in self.manage_listbox.get_children()
            if getattr(row, "chk", None) is not None and getattr(row, "key", None) is not None
            and row.chk.get_active()
        }
        for row in list(self.manage_listbox.get_children()):
            self.manage_listbox.remove(row)
        for entry in sorted(entries, key=lambda e: (e["source"], e["name"].lower())):
            row = Gtk.ListBoxRow()
            row.set_activatable(True)
            row.entry = entry
            row.key = (entry["source"], entry["id"], entry.get("desktop", ""))
            row.get_style_context().add_class("app-row")
            row.search_text = (entry["name"] + " " + entry["id"] + " " + entry["source"]).lower()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            chk = Gtk.CheckButton()
            protected = bool(entry.get("protected"))
            chk.set_sensitive(not protected)
            chk.set_tooltip_text("Essential desktop package, protected from removal" if protected
                                 else "Select " + entry["name"])
            self._accessible_name(chk, ("Protected " if protected else "Select ") + entry["name"])
            chk.set_active(not protected and row.key in previously_selected)
            chk.connect("toggled", lambda _c: self._update_manage_counter())
            line.pack_start(chk, False, False, 0)
            line.pack_start(self._app_icon(entry), False, False, 0)
            label = Gtk.Label(label=entry["name"])
            label.set_xalign(0)
            label.set_hexpand(True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_tooltip_text(entry["id"])
            label.get_style_context().add_class("settings-title")
            line.pack_start(label, True, True, 0)
            source = Gtk.Label(label={"apt": "APT", "snap": "Snap"}.get(
                entry["source"], "Flatpak"))
            source.get_style_context().add_class("badge")
            line.pack_start(source, False, False, 0)
            status = Gtk.Label(label="Protected" if protected else "Installed")
            status.get_style_context().add_class("status-warning" if protected else "status-installed")
            if protected:
                status.set_tooltip_text("A core package required by the desktop; removal is blocked")
            line.pack_start(status, False, False, 0)
            row.add(line)
            row.chk = chk
            row.status_label = status
            self.manage_listbox.add(row)
        self.manage_listbox.show_all()
        self._update_manage_counter()
        self._on_manage_search_changed(None)
        self._manage_count = len(entries)
        self._notice("Found {} installed app(s).".format(len(entries)))
        self.submit(apps_backend.list_updates, done=self._apply_manage_updates,
                    name="Checking for updates")

    def _apply_manage_updates(self, updates):
        """Badge rows whose source reports an update (best-effort, read-only)."""
        if not isinstance(updates, dict):
            return
        available = 0
        for row in self.manage_listbox.get_children():
            entry = getattr(row, "entry", None)
            if not entry or entry.get("protected"):
                continue
            ids = updates.get(entry.get("source"))
            if not ids or entry.get("id") not in ids:
                continue
            entry["updatable"] = True
            available += 1
            label = getattr(row, "status_label", None)
            if label is not None:
                label.set_text("Update available")
                label.get_style_context().add_class("status-warning")
                label.set_tooltip_text(
                    "A newer version is available; select it and press Update Selected")
        if available:
            self._notice("Found {} installed app(s); {} update(s) available.".format(
                getattr(self, "_manage_count", available), available))

    def _selected_manage(self):
        selected = []
        for row in self.manage_listbox.get_children():
            chk = getattr(row, "chk", None)
            if chk is not None and chk.get_active() and chk.get_sensitive():
                selected.append(row.entry)
        return selected

    def _on_manage_row_activated(self, _listbox, row):
        chk = getattr(row, "chk", None)
        if chk is not None and chk.get_sensitive():
            chk.set_active(not chk.get_active())
            self._update_manage_counter()

    def on_manage_select_all(self, _btn):
        query = self.manage_search.get_text().strip().lower()
        for row in self.manage_listbox.get_children():
            chk = getattr(row, "chk", None)
            if chk is None or not chk.get_sensitive():
                continue
            if not query or query in getattr(row, "search_text", ""):
                chk.set_active(True)
        self._update_manage_counter()

    def on_manage_select_none(self, _btn):
        query = self.manage_search.get_text().strip().lower()
        for row in self.manage_listbox.get_children():
            chk = getattr(row, "chk", None)
            if chk is not None and chk.get_sensitive() and \
                    (not query or query in getattr(row, "search_text", "")):
                chk.set_active(False)
        self._update_manage_counter()

    def on_uninstall_scanned(self, _btn):
        selected = self._selected_manage()
        if not selected:
            self._notify("Tick at least one installed app first.", "warning")
            return
        if not self._confirm("Uninstall {} package(s)?".format(len(selected)),
                             "\n".join("• {} ({})".format(e["name"], e["source"]) for e in selected)):
            return
        self.submit(apps_backend.uninstall_installed, selected,
                    done=lambda _r: self.on_scan_installed(), name="Uninstalling apps")

    def _select_updatable_rows(self):
        """Tick every row the update check flagged; returns the picked entries."""
        picked = []
        for row in self.manage_listbox.get_children():
            entry = getattr(row, "entry", None)
            chk = getattr(row, "chk", None)
            if entry and entry.get("updatable") and not entry.get("protected") \
                    and chk is not None and chk.get_sensitive():
                chk.set_active(True)
                picked.append(entry)
        if picked:
            self._update_manage_counter()
        return picked

    def on_update_scanned(self, _btn):
        selected = self._selected_manage()
        if not selected:
            # Nothing ticked: treat the button as "update everything flagged".
            selected = self._select_updatable_rows()
            if not selected:
                self._notify("No updates found. Use Scan Installed to refresh the list first.",
                             "warning")
                return
        self.submit(apps_backend.update_installed, selected, name="Updating apps")

    # ------------------------------------------------------------------
    # AppImages page
    # ------------------------------------------------------------------
    def _build_appimages_page(self):
        page = self._page(
            "appimages", "AppImages", "AppImages",
            "Install AppImage files you downloaded with a menu entry and icon. "
            "Installing an AppImage that is already installed replaces it, which is how you update.")

        toolbar = Gtk.Box(spacing=8)
        self.appimage_search = Gtk.SearchEntry()
        self.appimage_search.set_placeholder_text("Search AppImages")
        self.appimage_search.set_hexpand(True)
        self.appimage_search.connect("search-changed", self._on_appimage_search_changed)
        toolbar.pack_start(self.appimage_search, True, True, 0)
        toolbar.pack_start(self._button("Install from File…", self.on_pick_appimage,
                                        "Choose an AppImage file to install"), False, False, 0)
        toolbar.pack_start(self._button("Rescan", self.on_rescan_appimages,
                                        "Scan Downloads and installed AppImages again",
                                        icon="view-refresh-symbolic"), False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.appimage_empty = self._hint(
            "No AppImages found in Downloads. Drag a .AppImage onto the window "
            "or use Install from File…")
        self.appimage_empty.set_no_show_all(True)
        self.appimage_empty.hide()
        self.appimage_list = Gtk.ListBox()
        self.appimage_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.appimage_list.set_activate_on_single_click(True)
        self.appimage_list.connect("row-activated", self._on_appimage_row_activated)
        self.appimage_list.set_filter_func(self._appimage_filter, None)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("list-surface")
        scroller.add(self.appimage_list)
        page.pack_start(self.appimage_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.appimage_counter = self._counter("Nothing selected")
        self.appimage_counter.set_xalign(0)
        page.pack_start(self.appimage_counter, False, False, 0)
        self.appimage_buttons = {
            "install": self._button("Install Selected", self.on_appimage_install,
                                    "Install the selected AppImages with a menu entry "
                                    "(installing again updates an installed app)", primary=True),
            "uninstall": self._button("Uninstall Selected", self.on_appimage_uninstall,
                                      "Remove the selected AppImage installs", destructive=True),
        }
        actions = self._flow(*self.appimage_buttons.values())
        actions.get_style_context().add_class("action-bar")
        page.pack_start(actions, False, False, 0)
        page.pack_start(self._hint(
            "The AppImage file stays in Downloads; Preen installs a copy. Uninstalling deletes "
            "the copy only when Preen installed it — external AppImage setups keep their files."),
            False, False, 0)

        integration_frame, integration = self._frame("File manager integration", tight=True)
        scripts_row, self.fm_scripts_switch = self._toggle_row(
            "Right-click menu entries",
            "Show 'Install with Preen' and 'Run with Preen' in the file manager "
            "(applies immediately)")
        # State from disk first, connect second: the initial sync must not
        # enqueue a change.
        self.fm_scripts_switch.set_active(appimages_backend.filemanager_scripts_installed())
        self.fm_scripts_switch.connect("notify::active", self.on_toggle_fm_scripts)
        integration.add(scripts_row)
        self.fm_default_button = self._button(
            "Set as default", self.on_set_default_appimage,
            "Open .AppImage files with Preen when double-clicked")
        integration.add(self._value_row(
            "Open .AppImage files with Preen", self.fm_default_button,
            "Double-click offers Install or Run; the right-click menu stays available"))
        page.pack_start(integration_frame, False, False, 0)
        self._setup_downloads_monitor()
        self._update_appimage_counter()

    @staticmethod
    def _scan_appimages_worker(log=None):
        warnings = []
        downloads = appimages_backend.list_downloads(warnings, log)
        installed = appimages_backend.list_installed(warnings, log)
        return downloads, installed, warnings

    def on_rescan_appimages(self, _btn=None):
        self.submit(self._scan_appimages_worker, done=self._fill_appimage_rows,
                    name="Scanning AppImages")

    def on_pick_appimage(self, _btn):
        path = self._open_dialog("Choose an AppImage to install")
        if not path:
            return
        self.submit(appimages_backend.install_appimages, [path],
                    done=lambda _r: self.on_rescan_appimages(), name="Installing AppImage")

    def _appimage_filter(self, row, _data):
        query = self.appimage_search.get_text().strip().lower()
        if getattr(row, "is_header", False):
            return not query
        return not query or query in getattr(row, "search_text", "")

    def _on_appimage_search_changed(self, _entry):
        self.appimage_list.invalidate_filter()
        query = self.appimage_search.get_text().strip()
        visible = any(self._appimage_filter(row, None)
                      for row in self.appimage_list.get_children()
                      if not getattr(row, "is_header", False))
        self.appimage_empty.set_visible(not visible)
        if not visible:
            self.appimage_empty.set_text(
                "No AppImages match your search. Clear the search box to see them all."
                if query else
                "No AppImages found in Downloads. Drag a .AppImage onto the window "
                "or use Install from File…")
            self.appimage_empty.show()
        else:
            self.appimage_empty.hide()

    def _fill_appimage_rows(self, result):
        if isinstance(result, tuple) and len(result) == 3:
            downloads, installed, _warnings = result
        else:
            downloads, installed = [], []
        if not isinstance(downloads, list) or not isinstance(installed, list):
            return
        selected_keys = {
            row.key for row in self.appimage_list.get_children()
            if getattr(row, "chk", None) is not None and row.chk.get_active()
        }
        for row in list(self.appimage_list.get_children()):
            self.appimage_list.remove(row)
        for heading, rows in (("IN DOWNLOADS", downloads), ("INSTALLED", installed)):
            if not rows:
                continue
            header = Gtk.ListBoxRow()
            header.set_activatable(False)
            header.set_selectable(False)
            header.is_header = True
            header.get_style_context().add_class("list-header")
            heading_label = Gtk.Label(label=heading)
            heading_label.set_xalign(0)
            heading_label.get_style_context().add_class("settings-title")
            header.add(heading_label)
            self.appimage_list.add(header)
            for item in rows:
                self.appimage_list.add(
                    self._build_appimage_row(item, item["id"] in selected_keys))
        self.appimage_list.show_all()
        self._update_appimage_counter()
        self._on_appimage_search_changed(None)

    def _build_appimage_row(self, item, selected):
        row = Gtk.ListBoxRow()
        row.set_activatable(True)
        row.is_header = False
        row.key = item["id"]
        row.kind = item["kind"]
        row.entry = item
        row.get_style_context().add_class("app-row")
        row.search_text = (item["name"] + " " + item.get("version", "") + " "
                           + os.path.basename(item.get("path", ""))).lower()
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        chk = Gtk.CheckButton()
        chk.set_active(selected)
        chk.set_tooltip_text("Select " + item["name"])
        self._accessible_name(chk, "Select " + item["name"])
        chk.connect("toggled", lambda _c: self._update_appimage_counter())
        line.pack_start(chk, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name = Gtk.Label(label=item["name"])
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.get_style_context().add_class("settings-title")
        text.pack_start(name, False, False, 0)
        if item["kind"] == "download":
            caption = "{} · {}".format(os.path.basename(item["path"]), item["size"])
        else:
            caption = item["path"]
            if item.get("version"):
                caption = "{} · v{}".format(caption, item["version"])
        caption_label = Gtk.Label(label=caption)
        caption_label.set_xalign(0)
        caption_label.set_ellipsize(Pango.EllipsizeMode.END)
        caption_label.set_tooltip_text(caption)
        caption_label.get_style_context().add_class("hint-label")
        text.pack_start(caption_label, False, False, 0)
        line.pack_start(text, True, True, 0)

        if item["kind"] == "download":
            if item.get("installed"):
                badge = Gtk.Label(label="Installed — install again to update")
                badge.get_style_context().add_class("status-installed")
                badge.set_tooltip_text("An AppImage with this name is already installed; "
                                       "installing replaces it with this file")
            else:
                badge = Gtk.Label(label="Ready to install")
                badge.get_style_context().add_class("dim-label")
            line.pack_start(badge, False, False, 0)
        else:
            source = Gtk.Label(label="AppImage")
            source.get_style_context().add_class("badge")
            if not item.get("managed"):
                source.set_tooltip_text("Installed outside Preen; only the menu entry is removed")
            line.pack_start(source, False, False, 0)
        row.add(line)
        row.chk = chk
        return row

    def _selected_appimages(self):
        selected = []
        for row in self.appimage_list.get_children():
            chk = getattr(row, "chk", None)
            if chk is not None and chk.get_active():
                selected.append(row.entry)
        return selected

    def _on_appimage_row_activated(self, _listbox, row):
        chk = getattr(row, "chk", None)
        if chk is not None:
            chk.set_active(not chk.get_active())
            self._update_appimage_counter()

    def _update_appimage_counter(self):
        selected = self._selected_appimages()
        count = len(selected)
        self.appimage_counter.set_text("{} selected".format(count) if count else "Nothing selected")
        if not hasattr(self, "appimage_buttons"):
            return
        has_downloads = any(item["kind"] == "download" for item in selected)
        has_installed = any(item["kind"] == "installed" for item in selected)
        enabled = not self._busy
        self.appimage_buttons["install"].set_sensitive(enabled and has_downloads)
        self.appimage_buttons["uninstall"].set_sensitive(enabled and has_installed)

    def on_appimage_install(self, _btn):
        paths = [item["path"] for item in self._selected_appimages()
                 if item["kind"] == "download"]
        if not paths:
            self._notify("Tick at least one AppImage in Downloads first.", "warning")
            return
        self.submit(appimages_backend.install_appimages, paths,
                    done=lambda _r: self.on_rescan_appimages(), name="Installing AppImage")

    def on_appimage_uninstall(self, _btn):
        entries = [item for item in self._selected_appimages()
                   if item["kind"] == "installed"]
        if not entries:
            self._notify("Tick at least one installed AppImage first.", "warning")
            return
        if not self._confirm(
                "Remove {} AppImage install(s)?".format(len(entries)),
                "\n".join("• {}".format(e["name"]) for e in entries) +
                "\n\nThe AppImage file is deleted only when Preen installed it."):
            return
        self.submit(appimages_backend.uninstall_appimages, [e["id"] for e in entries],
                    done=lambda _r: self.on_rescan_appimages(), name="Uninstalling AppImages")

    def on_toggle_fm_scripts(self, switch, _param=None):
        self.submit(appimages_backend.set_filemanager_scripts, switch.get_active(),
                    done=lambda _r: self._sync_fm_state(), name="Updating file manager menu")

    def _sync_fm_state(self):
        installed = appimages_backend.filemanager_scripts_installed()
        if self.fm_scripts_switch.get_active() != installed:
            self.fm_scripts_switch.set_active(installed)

    def on_set_default_appimage(self, _btn):
        self.submit(appimages_backend.set_default_appimage_handler,
                    name="Setting default AppImage handler")

    def _setup_downloads_monitor(self):
        """Watch Downloads so a freshly downloaded AppImage is noticed."""
        try:
            directory = appimages_backend.downloads_dir()
            if not os.path.isdir(directory):
                return
            monitor = Gio.File.new_for_path(directory).monitor_directory(
                Gio.FileMonitorFlags.NONE, None)
            monitor.connect("changed", self._on_downloads_changed)
            self._downloads_monitor = monitor  # keep it alive for the window
        except Exception as exc:
            self.log_buf.append("[warning] Downloads watch unavailable: {}\n".format(exc))

    def _on_downloads_changed(self, _monitor, file, _other_file, event):
        if event not in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.RENAMED):
            return False
        name = file.get_basename() if file is not None else ""
        if not name.lower().endswith(".appimage"):
            return False
        # A download produces a storm of events; settle before reacting once.
        if self._downloads_pending:
            return False
        self._downloads_pending = True
        GLib.timeout_add_seconds(3, self._downloads_settled)
        return False

    def _downloads_settled(self):
        self._downloads_pending = False
        self.on_rescan_appimages()
        self._notify("New AppImage in Downloads — review it on the AppImages page.", "info")
        return False

    # ------------------------------------------------------------------
    # Drag and drop (first DnD target in Preen)
    # ------------------------------------------------------------------
    def _setup_drag_drop(self):
        """Accept .AppImage/.deb files dropped from a file manager."""
        try:
            targets = [Gtk.TargetEntry.new("text/uri-list", 0, 0)]
            self.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.COPY)
            self.connect("drag-data-received", self._on_drag_data_received)
        except Exception as exc:  # never let DnD setup break the window
            log = getattr(self, "log_buf", None)
            if log is not None:
                log.append("[warning] drag-and-drop unavailable: {}\n".format(exc))

    def _on_drag_data_received(self, _widget, _context, _x, _y, data, _info, _time):
        uris = data.get_uris() if data is not None else []
        self._handle_dropped_uris(uris)
        return True

    def _handle_dropped_uris(self, uris):
        paths = []
        for uri in uris or []:
            try:
                path = Gio.File.new_for_uri(uri).get_path()
            except Exception:
                path = None
            if path:
                paths.append(path)
        self._handle_dropped_files(paths)
        return False

    def _handle_dropped_files(self, paths):
        appimages, debs, ignored = [], [], []
        for path in paths or []:
            lower = path.lower()
            if lower.endswith(".appimage"):
                appimages.append(path)
            elif lower.endswith(".deb"):
                debs.append(path)
            else:
                ignored.append(os.path.basename(path))
        if ignored:
            self._notify("Dropped file(s) ignored: {}. Only .AppImage and .deb files are supported."
                         .format(", ".join(ignored[:3])), "warning")
        if appimages:
            try:
                self.stack.set_visible_child_name("appimages")
            except Exception:
                pass
            self.submit(appimages_backend.install_appimages, appimages,
                        done=lambda _r: self.on_rescan_appimages(), name="Installing AppImage")
        for path in debs:
            if self._confirm("Install {}?".format(os.path.basename(path)),
                             "Installs the package with apt-get (one polkit prompt)."):
                self.submit(appimages_backend.install_deb, path,
                            done=lambda _r: self.on_scan_installed(), name="Installing package")

    # ------------------------------------------------------------------
    # Optimize page
    # ------------------------------------------------------------------
    def _build_optimize_page(self):
        page = self._page(
            "optimize", "Optimize System", "Optimize System",
            "Only the settings you change are applied. Cleaning up and changing swap or ZRAM "
            "needs your password via polkit.", icon="speedometer-symbolic")

        cleanup_frame, cleanup = self._frame("Cleanup & desktop behaviour", tight=True)
        cleanup_row, self.chk_cleanup = self._toggle_row(
            "Remove unused packages",
            "APT autoremove and autoclean, plus unused Flatpak runtimes")
        animations_row, self.chk_animations = self._toggle_row(
            "Disable GNOME animations",
            "Fewer transitions and window effects on supported desktops")
        cleanup.pack_start(cleanup_row, False, False, 0)
        cleanup.pack_start(animations_row, False, False, 0)
        startup_row = Gtk.Box()
        startup_row.get_style_context().add_class("settings-row")
        startup_row.pack_start(
            self._button("Manage Startup Apps…", self.on_manage_startup,
                         "Enable or disable apps that launch at login", icon="list-add-symbolic",
                         flat=True),
            False, False, 0)
        cleanup.pack_start(startup_row, False, False, 0)
        page.pack_start(cleanup_frame, False, False, 0)

        power_frame, power = self._frame("Memory & power", tight=True)
        swap_row, self.chk_swap = self._toggle_row(
            "Use a swapfile",
            "Creates /swapfile; turning it off removes the file and its /etc/fstab entry",
            tooltip="Creates or removes /swapfile and its /etc/fstab entry")
        self.chk_swap.connect("notify::active", self._on_swap_toggle)
        power.pack_start(swap_row, False, False, 0)

        self.cmb_swap_size = Gtk.ComboBoxText()
        for size_gb in (1, 2, 4, 8):
            self.cmb_swap_size.append_text("{} GB".format(size_gb))
        self.cmb_swap_size.set_active(1)
        self.cmb_swap_size.set_tooltip_text("Swapfile size in gigabytes (only used when enabling it)")
        power.pack_start(self._value_row("Swapfile size", self.cmb_swap_size,
                                         "Only used when a swapfile is being enabled"),
                         False, False, 0)

        zram_row, self.chk_zram = self._toggle_row(
            "Enable ZRAM",
            "Needs systemd-zram-generator; existing custom configurations are preserved")
        power.pack_start(zram_row, False, False, 0)

        self.cmb_power = Gtk.ComboBoxText()
        for profile in perf_backend.POWER_PROFILES:
            self.cmb_power.append_text(profile)
        self.cmb_power.append_text("Unavailable")
        self.cmb_power.set_active(len(perf_backend.POWER_PROFILES))
        self.cmb_power.set_sensitive(False)
        self.cmb_power.set_tooltip_text("Requires a working power-profiles-daemon")
        power.pack_start(self._value_row("Power profile", self.cmb_power,
                                         "Requires power-profiles-daemon"),
                         False, False, 0)
        page.pack_start(power_frame, False, False, 0)
        self._on_swap_toggle(None)

        security_frame, security = self._frame("Security", tight=True)
        ufw_row, self.chk_ufw = self._toggle_row(
            "Firewall (UFW)",
            "Blocks unsolicited incoming connections")
        self.chk_ufw.set_sensitive(False)  # until the state read completes
        security.pack_start(ufw_row, False, False, 0)
        page.pack_start(security_frame, False, False, 0)

        page.pack_start(self._flow(
            self._button("Apply Changes", self.on_run_optimize,
                         "Apply only the settings you changed", primary=True,
                         icon="object-select-symbolic"),
            self._button("Reload Current Settings", self._refresh_optimize_settings,
                         "Re-read the current optimization settings"),
        ), False, False, 0)
        page.pack_start(self._hint(
            "Current settings are detected automatically. If nothing changed, nothing runs."),
            False, False, 0)

    def _on_swap_toggle(self, _switch, _param=None):
        # The size combo only matters while a swapfile is being enabled.
        self.cmb_swap_size.set_sensitive(self.chk_swap.get_active())

    def _sync_power_control(self):
        # An unavailable or failed daemon read is not a 'balanced' profile.
        available = self.baseline.get("power") in perf_backend.POWER_PROFILES
        self.cmb_power.set_sensitive(available and not self._busy)

    def _sync_ufw_control(self):
        # Unknown state (ufw missing or unreadable) stays insensitive.
        known = self.baseline.get("ufw") is not None
        self.chk_ufw.set_sensitive(known and not self._busy)

    def _read_optimize_settings(self):
        animations = system_backend.are_animations_enabled()
        return {
            "animations_off": None if animations is None else not animations,
            "swap": perf_backend.is_swapfile_active(),
            "zram": perf_backend.is_zram_active() or perf_backend.is_zram_configured(),
            "power": perf_backend.get_power_profile(),
            "ufw": firewall_backend.ufw_enabled(),
        }

    def _read_appearance_setting(self):
        return {
            "theme": settings_backend.get("appearance_mode"),
            "desktop_theme": ui_backend.get_theme_mode(),
        }

    def _read_look_settings(self):
        info = self._read_appearance_setting()
        info.update({
            "round": ui_backend.are_rounded_corners_enabled(),
            "scaling": ui_backend.get_text_scaling(),
        })
        return info

    def _read_settings(self):
        info = self._read_optimize_settings()
        info.update(self._read_look_settings())
        info["warnings"] = dash_backend.feature_warnings()
        return info

    def _apply_optimize_settings(self, info):
        if not isinstance(info, dict):
            return
        self.baseline.update(info)
        animations = info.get("animations_off")
        self.chk_animations.set_active(bool(animations))
        self.chk_animations.set_sensitive(animations is not None)
        self.chk_animations.set_tooltip_text(
            "Current animation setting could not be read" if animations is None else
            "Fewer transitions and window effects on supported desktops")
        self.chk_swap.set_active(bool(info.get("swap")))
        self.chk_zram.set_active(bool(info.get("zram")))
        profile = info.get("power")
        if profile in perf_backend.POWER_PROFILES:
            self.cmb_power.set_active(perf_backend.POWER_PROFILES.index(profile))
        else:
            self.cmb_power.set_active(len(perf_backend.POWER_PROFILES))
        self._sync_power_control()
        self._on_swap_toggle(None)
        ufw = info.get("ufw")
        self.chk_ufw.set_active(bool(ufw))
        self.chk_ufw.set_sensitive(ufw is not None)
        self.chk_ufw.set_tooltip_text(
            "UFW is not installed" if ufw is None else
            "Firewall is currently " + ("active" if ufw else "inactive"))

    def _apply_theme_setting(self, mode):
        if mode not in settings_backend.VALID_APPEARANCE:
            mode = "system"
        self.baseline["theme"] = mode
        self.settings["appearance_mode"] = mode
        self.cmb_theme.set_active({"system": 0, "light": 1, "dark": 2}[mode])
        effective = (self._desktop_theme or "dark") if mode == "system" else mode
        self._set_app_theme(effective)

    def _apply_appearance_setting(self, info):
        if not isinstance(info, dict):
            return
        if info.get("desktop_theme") in ("light", "dark"):
            self._desktop_theme = info["desktop_theme"]
        self._apply_theme_setting(info.get("theme"))

    def _apply_look_settings(self, info):
        if not isinstance(info, dict):
            return
        self.baseline.update(info)
        self._apply_appearance_setting(info)
        self.chk_round.set_active(bool(info.get("round")))
        current = info.get("scaling")
        if self._extra_scaling_option:
            self.cmb_scaling.remove(len(self.SCALING_OPTIONS))
            self._extra_scaling_option = False
        index = next((i for i, (_label, factor) in enumerate(self.SCALING_OPTIONS)
                      if current is not None and abs(factor - current) < 0.000001), None)
        if index is None:
            label = "Unavailable" if current is None else "Custom ({:g}%)".format(current * 100)
            self.cmb_scaling.append_text(label)
            self._extra_scaling_option = True
            index = len(self.SCALING_OPTIONS)
        self.cmb_scaling.set_active(index)
        self.cmb_scaling.set_sensitive(current is not None)

    def _apply_settings(self, info):
        if not isinstance(info, dict):
            return
        self._apply_optimize_settings({key: info.get(key) for key in
                                       ("animations_off", "swap", "zram", "power")})
        self._apply_look_settings({key: info.get(key) for key in
                                   ("theme", "desktop_theme", "round", "scaling")})
        warnings = info.get("warnings") or []
        for child in list(self.health_chips.get_children()):
            self.health_chips.remove(child)
        if warnings:
            self.health_chips.pack_start(
                self._chip("Tool availability · {} need attention".format(len(warnings)),
                           "status-warning"), False, False, 0)
            self.lbl_health.set_text("\n".join("• " + w for w in warnings))
            self.health_box.set_no_show_all(False)
            self.health_box.show_all()
            self.health_box.show()
            if self.settings.get("show_dependency_warnings", True):
                self._notify(
                    "Some tools are unavailable. See the Dashboard for details.", "warning")
        else:
            self.health_box.hide()
            self.health_box.set_no_show_all(True)

    def _refresh_settings(self, *_args):
        self.submit(self._read_settings, done=self._apply_settings, name="Reading settings")

    def _refresh_optimize_settings(self, *_args):
        self.submit(self._read_optimize_settings, done=self._apply_optimize_settings,
                    name="Reading current settings")

    def _refresh_look_settings(self, *_args):
        self.submit(self._read_look_settings, done=self._apply_look_settings,
                    name="Reading look settings")

    def _refresh_theme_setting(self, *_args):
        self.submit(self._read_appearance_setting, done=self._apply_appearance_setting,
                    name="Reading appearance settings")

    def on_run_optimize(self, _btn):
        opts = {
            "cleanup": self.chk_cleanup.get_active(),
            "animations_off": self.chk_animations.get_active(),
            "swap": self.chk_swap.get_active(),
            "swap_size": self._swap_size(),
            "zram": self.chk_zram.get_active(),
            "power": self.cmb_power.get_active_text(),
            "ufw": self.chk_ufw.get_active(),
        }
        actions = []
        if opts["cleanup"]:
            actions.append(("System cleanup", system_backend.run_cleanup, ()))
        if (self.baseline.get("animations_off") is not None and
                opts["animations_off"] != self.baseline["animations_off"]):
            actions.append(("GNOME animations", system_backend.set_animations,
                            (not opts["animations_off"],)))
        if (self.baseline.get("power") in perf_backend.POWER_PROFILES
                and opts["power"] in perf_backend.POWER_PROFILES
                and opts["power"] != self.baseline["power"]):
            actions.append(("Power profile", perf_backend.set_power_profile, (opts["power"],)))
        if opts["swap"] != self.baseline.get("swap"):
            actions.append(("Swapfile", perf_backend.enable_swapfile if opts["swap"] else perf_backend.disable_swapfile,
                            (opts["swap_size"],) if opts["swap"] else ()))
        if opts["zram"] != self.baseline.get("zram"):
            actions.append(("ZRAM", perf_backend.enable_zram if opts["zram"] else perf_backend.disable_zram, ()))
        ufw_baseline = self.baseline.get("ufw")
        if ufw_baseline is not None and opts["ufw"] != bool(ufw_baseline):
            actions.append(("Firewall (UFW)", firewall_backend.set_ufw, (opts["ufw"],)))
        if not actions:
            self._notify("Nothing to apply. Your settings already match.", "info")
            return
        risks = []
        if opts["cleanup"]:
            risks.append("Cleanup removes unused packages and Flatpak runtimes.")
        if not opts["swap"] and self.baseline.get("swap"):
            risks.append("The active /swapfile will be disabled and permanently removed.")
        if not opts["zram"] and self.baseline.get("zram"):
            risks.append("Preen-managed ZRAM will be stopped and its configuration removed.")
        if ufw_baseline and not opts["ufw"]:
            risks.append("The firewall will be disabled; unsolicited incoming connections "
                         "will no longer be blocked.")
        if risks and not self._confirm("Apply system changes?", "\n".join(risks)):
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_optimize_settings(),
                    name="Applying system settings")

    def on_manage_startup(self, _btn):
        self.submit(system_backend.list_startup_apps, done=self._show_startup_dialog,
                    name="Listing startup apps")

    def _show_startup_dialog(self, items):
        if items is None:
            self._notify("Startup applications could not be read. See Logs for details.", "warning")
            return
        if not isinstance(items, list):
            return  # the worker has already reported its error
        if not items:
            self._notify("No autostart entries were found on this system.", "info")
            return
        dialog = Gtk.Dialog(title="Startup Applications", parent=self, flags=0,
                            use_header_bar=True)
        dialog.set_default_size(560, 480)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_APPLY, Gtk.ResponseType.APPLY)
        dialog.get_content_area().pack_start(
            self._hint("Turn off anything you do not want launching at login."), False, False, 6)
        scroll = Gtk.ScrolledWindow()
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_border_width(10)
        scroll.add(vbox)
        toggles = []
        for item in items:
            line = Gtk.Box(spacing=8)
            label = Gtk.Label(label=item["name"])
            label.set_xalign(0)
            label.set_hexpand(True)
            switch = Gtk.Switch()
            self._accessible_name(switch, "Start " + item["name"] + " at login")
            switch.set_active(item["enabled"])
            line.pack_start(label, True, True, 0)
            line.pack_start(switch, False, False, 0)
            vbox.pack_start(line, False, False, 0)
            toggles.append((switch, item))
        dialog.show_all()
        response = dialog.run()
        changes = [(switch.get_active(), item) for switch, item in toggles
                   if switch.get_active() != item["enabled"]]
        dialog.destroy()
        if response != Gtk.ResponseType.APPLY or not changes:
            return
        actions = [("Startup: " + item["name"], system_backend.set_startup_app,
                    (item["path"], enabled)) for enabled, item in changes]
        self.submit(utils.run_actions, actions, name="Updating startup apps")

    # ------------------------------------------------------------------
    # Customize page
    # ------------------------------------------------------------------
    def _build_customize_page(self):
        page = self._page(
            "customize", "Customize Look", "Customize Look",
            "Choose Preen's appearance without changing your desktop. "
            "Optional desktop-wide settings are grouped separately below.",
            icon="preferences-desktop-appearance")

        theme_frame, theme = self._frame("Preen appearance", tight=True)
        self.cmb_theme = Gtk.ComboBoxText()
        self._accessible_name(self.cmb_theme, "Preen appearance")
        for label in ("Follow system", "Light", "Dark"):
            self.cmb_theme.append_text(label)
        self.cmb_theme.set_active(0)
        self.cmb_theme.set_tooltip_text("Changes Preen only; does not change GNOME or other apps")
        theme.pack_start(self._value_row("Appearance", self.cmb_theme,
                                         "Preen only · Follow system reads, but never changes, GNOME"),
                         False, False, 0)
        page.pack_start(theme_frame, False, False, 0)

        extras_frame, extras = self._frame("Desktop-wide options", tight=True)
        extras.pack_start(self._hint(
            "These optional settings affect other applications. You will be asked before applying them."),
            False, False, 0)
        self.SCALING_OPTIONS = (
            ("Default (100%)", 1.0),
            ("Large (115%)", 1.15),
            ("Larger (125%)", 1.25),
            ("Small (85%)", 0.85),
        )
        self.cmb_scaling = Gtk.ComboBoxText()
        self._accessible_name(self.cmb_scaling, "Desktop text size")
        self._extra_scaling_option = False
        for label, _factor in self.SCALING_OPTIONS:
            self.cmb_scaling.append_text(label)
        self.cmb_scaling.set_active(0)
        self.cmb_scaling.set_tooltip_text("GNOME text scaling factor, applied desktop-wide")
        extras.pack_start(self._value_row("Desktop text size", self.cmb_scaling,
                                          "GNOME scaling factor, applied to other apps too"),
                          False, False, 0)
        round_row, self.chk_round = self._toggle_row(
            "Rounded GTK corners",
            "Adds a reversible rule to ~/.config/gtk-3.0/gtk.css for GTK 3 apps")
        extras.pack_start(round_row, False, False, 0)
        icon_row = Gtk.Box()
        icon_row.get_style_context().add_class("settings-row")
        icon_row.pack_start(self._button("Install Desktop Icon Pack…", self.on_install_icon,
                                         "Install and activate an icon theme for the desktop",
                                         icon="folder-download-symbolic", flat=True),
                            False, False, 0)
        extras.pack_start(icon_row, False, False, 0)
        extras.pack_start(self._hint("Desktop GTK corner changes may need an app restart to show."),
                          False, False, 0)
        page.pack_start(extras_frame, False, False, 0)

        page.pack_start(self._flow(
            self._button("Apply Look Changes", self.on_apply_look,
                         "Apply staged changes; desktop-wide changes require confirmation", primary=True,
                         icon="object-select-symbolic"),
            self._button("Reload Current Look", self._refresh_look_settings,
                         "Re-read Preen and desktop look settings"),
        ), False, False, 0)

    def _theme_mode(self):
        index = self.cmb_theme.get_active()
        modes = settings_backend.VALID_APPEARANCE
        return modes[index] if 0 <= index < len(modes) else None

    def on_apply_look(self, _btn):
        mode = self._theme_mode()
        actions = []
        if mode is not None and mode != self.baseline.get("theme"):
            actions.append(("Theme", ui_backend.apply_theme_mode, (mode,)))
        if self.chk_round.get_active() != self.baseline.get("round"):
            actions.append(("Rounded corners", ui_backend.set_rounded_corners,
                            (self.chk_round.get_active(),)))
        index = self.cmb_scaling.get_active()
        if 0 <= index < len(self.SCALING_OPTIONS) and self.baseline.get("scaling") is not None:
            scaling = self.SCALING_OPTIONS[index][1]
            if abs(scaling - self.baseline["scaling"]) > 0.000001:
                actions.append(("Text size", ui_backend.set_text_scaling, (scaling,)))
        if not actions:
            self._notify("Nothing to apply. Your look already matches.", "info")
            return
        desktop_changes = [label for label, _func, _args in actions if label != "Theme"]
        if desktop_changes and not self._confirm(
                "Apply desktop-wide look changes?",
                "{} affect other applications, not just Preen. "
                "The rounded-corner rule changes GTK 3 user CSS; text size changes GNOME scaling."
                .format(", ".join(desktop_changes))):
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_look_settings(),
                    name="Applying look changes")

    def on_install_icon(self, _btn):
        dialog = Gtk.FileChooserDialog(title="Select icon pack", parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and path and self._confirm(
                "Install and activate a desktop icon pack?",
                "This installs the archive in ~/.icons and changes the GNOME icon theme "
                "for other applications, not just Preen."):
            self.submit(ui_backend.install_icon_pack, path, name="Installing icon pack")

    # ------------------------------------------------------------------
    # Deep Clean page
    # ------------------------------------------------------------------
    def _build_deepclean_page(self):
        page = self._page(
            "deepclean", "Deep Clean", "Deep Clean",
            "Review and remove selected caches, temporary files and logs. "
            "Scanned sizes are estimates, not a guarantee of recovered space.")

        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        summary.get_style_context().add_class("hero-card")
        caption = Gtk.Label(label="ESTIMATED RECLAIMABLE SPACE")
        caption.set_xalign(0)
        caption.get_style_context().add_class("eyebrow")
        self.clean_total = Gtk.Label(label="—")
        self.clean_total.set_xalign(0)
        self.clean_total.get_style_context().add_class("summary-value")
        self.clean_summary = Gtk.Label(label="Scanning cleanup items…")
        self.clean_summary.set_xalign(0)
        self.clean_summary.get_style_context().add_class("summary-caption")
        summary.pack_start(caption, False, False, 0)
        summary.pack_start(self.clean_total, False, False, 0)
        summary.pack_start(self.clean_summary, False, False, 0)
        page.pack_start(summary, False, False, 0)

        tools = Gtk.Box(spacing=8)
        heading = Gtk.Label(label="CLEANUP ITEMS")
        heading.set_xalign(0)
        heading.get_style_context().add_class("eyebrow")
        tools.pack_start(heading, True, True, 0)
        tools.pack_end(self._header_button("Clear", self.on_clean_select_none,
                                            "Clear the cleanup selection"), False, False, 0)
        tools.pack_end(self._header_button("Select all", self.on_clean_select_all,
                                            "Select items with a measured size"), False, False, 0)
        page.pack_start(tools, False, False, 0)
        self.clean_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("list-surface")
        scroller.add(self.clean_rows)
        page.pack_start(scroller, True, True, 0)

        self.clean_counter = self._counter("No items selected")
        self.clean_counter.set_xalign(0)
        page.pack_start(self.clean_counter, False, False, 0)
        self.clean_button = self._button("Clean Selected", self.on_clean_selected,
                                         "Clean the selected items after confirmation",
                                         primary=True, icon="user-trash-symbolic")
        actions = self._flow(
            self._button("Scan Now", self.on_scan_cleanable,
                         "Measure cleanup items again", icon="view-refresh-symbolic"),
            self.clean_button,
        )
        actions.get_style_context().add_class("action-bar")
        page.pack_start(actions, False, False, 0)
        self._update_clean_counter()

        maintenance_frame, maintenance = self._frame("Automatic maintenance", tight=True)
        maintenance_row, self.chk_maintenance = self._toggle_row(
            "Run cleanup automatically",
            "The root-level cleanup tasks on a schedule: package cache, unused "
            "packages, system journal and unused Flatpak runtimes")
        self.chk_maintenance.connect("notify::active", self.on_toggle_maintenance)
        self.chk_maintenance.set_sensitive(False)  # until the schedule read completes
        maintenance.pack_start(maintenance_row, False, False, 0)
        self.cmb_maintenance = Gtk.ComboBoxText()
        self._accessible_name(self.cmb_maintenance, "Maintenance frequency")
        for label in ("Daily", "Weekly", "Monthly"):
            self.cmb_maintenance.append_text(label)
        self.cmb_maintenance.set_active(1)  # Weekly
        self.cmb_maintenance.set_tooltip_text("How often automatic maintenance runs")
        self.cmb_maintenance.connect("changed", self.on_maintenance_frequency_changed)
        maintenance.pack_start(self._value_row("Frequency", self.cmb_maintenance,
                                               "How often automatic maintenance runs"),
                               False, False, 0)
        maintenance.pack_start(self._hint(
            "Uses a systemd timer, applies after one administrator prompt and runs even "
            "when Preen is closed. Simulate mode previews the change without touching the system."),
            False, False, 0)
        page.pack_start(maintenance_frame, False, False, 0)

    def on_clean_select_all(self, _btn=None):
        for chk, item in self.clean_checkbuttons.values():
            if chk.get_sensitive() and (item.get("size") or 0) > 0:
                chk.set_active(True)
        self._update_clean_counter()

    def on_clean_select_none(self, _btn=None):
        for chk, _item in self.clean_checkbuttons.values():
            chk.set_active(False)
        self._update_clean_counter()

    @staticmethod
    def _on_click_toggle_row(_eventbox, _event, chk):
        """Row-click toggles the checkbox; the checkbox consumes its own clicks."""
        chk.set_active(not chk.get_active())
        return False

    def _selected_clean_items(self):
        return [item for chk, item in self.clean_checkbuttons.values()
                if chk.get_active() and chk.get_sensitive()]

    def _update_clean_counter(self, *_args):
        selected = self._selected_clean_items()
        if not selected:
            self.clean_counter.set_text("No items selected")
        else:
            total = deepclean_backend.total_size(selected)
            unknown = any(item.get("size") is None for item in selected)
            measured = any(item.get("size") is not None for item in selected)
            if unknown and not measured:
                estimate = "size unavailable"
            elif unknown:
                estimate = "{} measured + unknown".format(deepclean_backend.format_size(total))
            else:
                estimate = "up to {} estimated".format(deepclean_backend.format_size(total))
            self.clean_counter.set_text("{} selected · {}".format(len(selected), estimate))
        if hasattr(self, "clean_button"):
            self.clean_button.set_sensitive(not self._busy and bool(selected))

    def _apply_clean_scan(self, items):
        if not isinstance(items, list):
            return
        selected_keys = {item["key"] for item in self._selected_clean_items()}
        for child in list(self.clean_rows.get_children()):
            self.clean_rows.remove(child)
        self.clean_checkbuttons = {}
        groups = (
            ("SYSTEM PACKAGES & LOGS", {"apt_cache", "journal", "old_kernels"}),
            ("REGENERABLE CACHES", {"thumbnails", "pip_cache"}),
            ("PERSONAL DATA", {"trash"}),
        )
        for group_name, keys in groups:
            group = [item for item in items if item.get("key") in keys]
            if not group:
                continue
            header = Gtk.Label(label=group_name)
            header.set_xalign(0)
            header.get_style_context().add_class("eyebrow")
            header.get_style_context().add_class("list-header")
            self.clean_rows.pack_start(header, False, False, 0)
            for item in group:
                line = Gtk.Box(spacing=10)
                line.get_style_context().add_class("clean-row")
                chk = Gtk.CheckButton()
                chk.set_valign(Gtk.Align.CENTER)
                size_value = item.get("size")
                chk.set_sensitive(size_value is None or size_value > 0)
                if size_value is None:
                    tooltip = "Size unavailable; select manually if you still want to clean this item"
                elif size_value > 0:
                    tooltip = "Select " + item["label"]
                else:
                    tooltip = "No measurable space found"
                chk.set_tooltip_text(tooltip)
                self._accessible_name(chk, "Select " + item["label"])
                chk.set_active(item["key"] in selected_keys and chk.get_sensitive())
                chk.connect("toggled", self._update_clean_counter)
                line.pack_start(chk, False, False, 0)
                text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                name = Gtk.Label(label=item["label"])
                name.set_xalign(0)
                name.get_style_context().add_class("settings-title")
                text_box.pack_start(name, False, False, 0)
                detail = Gtk.Label(label=item["detail"])
                detail.set_xalign(0)
                detail.set_ellipsize(Pango.EllipsizeMode.END)
                detail.set_tooltip_text(item["detail"])
                detail.get_style_context().add_class("hint-label")
                text_box.pack_start(detail, False, False, 0)
                if item.get("root") or item["key"] == "trash":
                    risk = Gtk.Label(label="Requires administrator access" if item.get("root")
                                     else "Permanently deletes trash contents")
                    risk.set_xalign(0)
                    risk.get_style_context().add_class("status-warning")
                    text_box.pack_start(risk, False, False, 0)
                size = Gtk.Label(label=deepclean_backend.format_size(size_value))
                size.set_tooltip_text("Estimated size; journal usage is an upper bound" if size_value is not None
                                      else "This item could not be measured")
                line.pack_start(text_box, True, True, 0)
                line.pack_end(size, False, False, 0)
                if chk.get_sensitive():
                    # A click anywhere on the row toggles it; clicks on the
                    # checkbox itself are consumed by the checkbox first.
                    clickable = Gtk.EventBox()
                    clickable.add(line)
                    clickable.connect("button-press-event", self._on_click_toggle_row, chk)
                    self.clean_rows.pack_start(clickable, False, False, 0)
                else:
                    self.clean_rows.pack_start(line, False, False, 0)
                self.clean_checkbuttons[item["key"]] = (chk, item)
        self.clean_rows.show_all()
        available = sum(1 for item in items if (item.get("size") or 0) > 0)
        unknown = sum(1 for item in items if item.get("size") is None)
        known = len(items) - unknown
        total = deepclean_backend.format_size(deepclean_backend.total_size(items))
        self.clean_total.set_text((total + " + unknown") if unknown and known else
                                  "Unavailable" if unknown else total)
        summary = "{} item(s) with measurable space · sizes are estimates".format(available)
        if unknown:
            summary += " · {} size(s) unavailable".format(unknown)
        self.clean_summary.set_text(summary)
        self._update_clean_counter()

    def on_scan_cleanable(self, _btn=None):
        self.submit(deepclean_backend.scan_cleanable, done=self._apply_clean_scan,
                    name="Scanning cleanup items")

    def on_clean_selected(self, _btn):
        selected = self._selected_clean_items()
        if not selected:
            self._notify("Select at least one item to clean.", "warning")
            return
        actions = deepclean_backend.build_clean_actions(selected)
        if not actions:
            self._notify("Nothing selected can be cleaned.", "warning")
            return
        if not self._confirm(
                "Clean {} item(s)?".format(len(selected)),
                "Deletes the selected caches and trash contents. This cannot be undone."):
            return
        was_simulated = utils.is_simulate()
        before = {item["key"]: item["size"] for item in selected}

        def finished(result):
            if was_simulated:
                if isinstance(result, utils.Outcome) and result.ok:
                    self._notify("Simulation complete. No files were removed; see Logs for the preview.", "info")
                return
            if isinstance(result, utils.Outcome) and result.ok:
                self.submit(deepclean_backend.scan_cleanable,
                            done=lambda items: self._after_clean_scan(items, before))
            else:
                self.on_scan_cleanable()

        self.submit(utils.run_actions, actions, done=finished, name="Cleaning selected items")

    def _after_clean_scan(self, items, before):
        if not isinstance(items, list):
            return
        after = {item["key"]: item["size"] for item in items}
        self._apply_clean_scan(items)
        if any(before[key] is None or after.get(key) is None for key in before):
            self._notify("Cleanup completed; a size comparison is unavailable.", "info")
            return
        difference = max(0, sum(before.values()) - sum(after[key] for key in before))
        self._notify("Cleanup completed. Selected items now measure {} less (estimated).".format(
            deepclean_backend.format_size(difference)), "info")

    # ------------------------------------------------------------------
    # Automatic maintenance (systemd timer)
    # ------------------------------------------------------------------
    MAINTENANCE_FREQUENCIES = ("daily", "weekly", "monthly")

    def _maintenance_frequency(self):
        index = self.cmb_maintenance.get_active()
        if not isinstance(index, int) or not 0 <= index < len(self.MAINTENANCE_FREQUENCIES):
            index = self.MAINTENANCE_FREQUENCIES.index("weekly")
        return self.MAINTENANCE_FREQUENCIES[index]

    def _apply_maintenance_state(self, schedule):
        if not isinstance(schedule, dict):
            return
        self._maintenance_baseline = schedule
        self.chk_maintenance.set_active(bool(schedule.get("enabled")))
        self.chk_maintenance.set_sensitive(True)
        frequency = schedule.get("frequency")
        if frequency in self.MAINTENANCE_FREQUENCIES:
            self.cmb_maintenance.set_active(self.MAINTENANCE_FREQUENCIES.index(frequency))
        if schedule.get("installed") and schedule.get("calendar"):
            self.cmb_maintenance.set_tooltip_text(
                "Currently scheduled: {}".format(schedule["calendar"]))

    def _sync_maintenance_control(self):
        known = getattr(self, "_maintenance_baseline", None) is not None
        self.chk_maintenance.set_sensitive(known and not self._busy)

    def _refresh_maintenance_state(self):
        self.submit(maintenance_backend.get_schedule, done=self._apply_maintenance_state,
                    name="Reading maintenance schedule")

    def on_toggle_maintenance(self, switch, _param=None):
        desired = switch.get_active()
        baseline = getattr(self, "_maintenance_baseline", None)
        if baseline is None:
            switch.handler_block_by_func(self.on_toggle_maintenance)
            switch.set_active(False)
            switch.handler_unblock_by_func(self.on_toggle_maintenance)
            return
        if bool(baseline.get("enabled")) == desired:
            return  # a programmatic sync or nothing to do
        if desired and not self._confirm(
                "Enable automatic maintenance?",
                "Preen installs a systemd timer that runs the root-level cleanup tasks "
                "on the chosen schedule. This applies immediately.",
                required=False):
            switch.handler_block_by_func(self.on_toggle_maintenance)
            switch.set_active(bool(baseline.get("enabled")))
            switch.handler_unblock_by_func(self.on_toggle_maintenance)
            return
        self.submit(maintenance_backend.set_schedule, desired, self._maintenance_frequency(),
                    done=lambda _r: self._refresh_maintenance_state(),
                    name="Updating maintenance schedule")

    def on_maintenance_frequency_changed(self, _combo=None):
        baseline = getattr(self, "_maintenance_baseline", None)
        if baseline is None or not baseline.get("enabled") \
                or not self.chk_maintenance.get_active():
            return
        if self._maintenance_frequency() == baseline.get("frequency"):
            return  # the applied state re-selected this row; nothing to do
        self.submit(maintenance_backend.set_schedule, True, self._maintenance_frequency(),
                    done=lambda _r: self._refresh_maintenance_state(),
                    name="Updating maintenance schedule")

    # ------------------------------------------------------------------
    # Services & Boot page
    # ------------------------------------------------------------------
    def _build_services_page(self):
        page = self._page(
            "services", "Services", "Services & Boot",
            "See what slows down your boot and manage systemd services. Changes need "
            "your password via polkit; core services can affect your desktop.",
            icon="system-run-symbolic")

        boot_card, boot_inner = self._frame("Boot time", icon="system-shutdown-symbolic")
        self.lbl_boot = Gtk.Label(label="Measuring boot time…")
        self.lbl_boot.set_xalign(0)
        self.lbl_boot.get_style_context().add_class("hint-label")
        self.boot_blame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        boot_inner.pack_start(self.lbl_boot, False, False, 0)
        boot_inner.pack_start(self.boot_blame, False, False, 0)
        page.pack_start(boot_card, False, False, 0)

        services_card, services_inner = self._frame(
            "System services", icon="system-run-symbolic")
        toolbar = Gtk.Box(spacing=8)
        self.services_search = Gtk.SearchEntry()
        self.services_search.set_placeholder_text("Search services…")
        self.services_search.set_hexpand(True)
        self.services_search.connect("search-changed", self._on_services_filter_changed)
        toolbar.pack_start(self.services_search, True, True, 0)
        self.chk_running_only = Gtk.CheckButton.new_with_label("Running only")
        self.chk_running_only.set_tooltip_text("Hide services that are not currently active")
        self.chk_running_only.connect("toggled", self._on_services_filter_changed)
        toolbar.pack_start(self.chk_running_only, False, False, 0)
        toolbar.pack_start(self._button("Refresh", self.on_refresh_services,
                                        "Re-read the service list", icon="view-refresh-symbolic"),
                           False, False, 0)
        services_inner.pack_start(toolbar, False, False, 0)

        self.services_count = self._hint("Loading services…")
        self._services_available = None
        services_inner.pack_start(self.services_count, False, False, 0)

        self.services_listbox = Gtk.ListBox()
        self.services_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.services_listbox.set_filter_func(self._services_filter, None)
        self.services_listbox.connect("row_selected", self._on_service_row_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(260)
        scroller.add(self.services_listbox)
        services_inner.pack_start(scroller, True, True, 0)
        page.pack_start(services_card, True, True, 0)

        self.service_buttons = {}
        for action, label, tooltip in (
            ("start", "Start", "Start the selected service"),
            ("stop", "Stop", "Stop the selected service"),
            ("restart", "Restart", "Restart the selected service"),
            ("enable", "Enable", "Enable the selected service at boot"),
            ("disable", "Disable", "Disable the selected service at boot"),
        ):
            self.service_buttons[action] = self._button(
                label, lambda _button, value=action: self.on_service_action(value), tooltip)
        page.pack_start(self._flow(*self.service_buttons.values()), False, False, 0)
        self._update_service_actions()
        page.pack_start(self._hint(
            "Green means running, red means failed, grey means stopped. Only change "
            "services you understand, since some are needed for sound, networking or the desktop."),
            False, False, 0)

    def _on_services_filter_changed(self, _widget=None):
        self.services_listbox.invalidate_filter()
        if self._services_available is False:
            self.services_count.set_text("Services unavailable. Check Logs for details, then try Refresh.")
            return
        visible = sum(1 for row in self.services_listbox.get_children()
                      if self._services_filter(row, None))
        total = len(self.services_listbox.get_children())
        self.services_count.set_text(
            "Showing {} of {} service(s)".format(visible, total))

    def _services_filter(self, row, _data):
        if not hasattr(row, "search_text"):
            return True
        if self.chk_running_only.get_active() and not getattr(row, "is_running", False):
            return False
        query = self.services_search.get_text().strip().lower()
        return not query or query in row.search_text

    def _on_service_row_selected(self, _box, row):
        self.selected_service_row = row
        self._update_service_actions()

    def _update_service_actions(self):
        if hasattr(self, "service_buttons"):
            for button in self.service_buttons.values():
                button.set_sensitive(not self._busy and self.selected_service_row is not None)

    def _apply_services(self, entries):
        self._services_available = isinstance(entries, list)
        self.selected_service_row = None
        self._update_service_actions()
        for child in list(self.services_listbox.get_children()):
            self.services_listbox.remove(child)
        if not self._services_available:
            self._on_services_filter_changed()
            return
        for entry in entries:
            row = Gtk.ListBoxRow()
            row.unit = entry["unit"]
            row.is_running = entry["active"] == "active"
            row.search_text = (entry["unit"] + " " + entry["description"]).lower()
            row.get_style_context().add_class("app-row")
            line = Gtk.Box(spacing=10)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            name = Gtk.Label(label=entry["unit"].replace(".service", ""))
            name.set_xalign(0)
            text_box.pack_start(name, False, False, 0)
            desc = Gtk.Label(label=entry["description"])
            desc.set_xalign(0)
            desc.set_ellipsize(Pango.EllipsizeMode.END)
            desc.get_style_context().add_class("hint-label")
            text_box.pack_start(desc, False, False, 0)
            line.pack_start(text_box, True, True, 0)
            active_chip = Gtk.Label(label=entry["active"] + " · " + entry["sub"])
            active_chip.get_style_context().add_class("chip")
            if entry["active"] == "active":
                active_chip.get_style_context().add_class("chip-ok")
            elif entry["active"] == "failed":
                active_chip.get_style_context().add_class("chip-bad")
            else:
                active_chip.get_style_context().add_class("chip-muted")
            line.pack_start(active_chip, False, False, 0)
            if entry.get("unit_state"):
                state = Gtk.Label(label=entry["unit_state"])
                state.get_style_context().add_class("badge")
                line.pack_start(state, False, False, 0)
            row.add(line)
            self.services_listbox.add(row)
        self.services_listbox.show_all()
        self._on_services_filter_changed(None)

    def _apply_boot(self, info):
        for child in list(self.boot_blame.get_children()):
            self.boot_blame.remove(child)
        if not isinstance(info, dict) or not info.get("total"):
            self.lbl_boot.set_text("Boot-time data is unavailable. Check Logs for details.")
            return
        phases = "  ·  ".join(
            "{} {}".format(info[key], key) for key in
            ("firmware", "loader", "kernel", "userspace") if info.get(key))
        self.lbl_boot.set_text(
            "Total boot: {}  ·  {}".format(info["total"], phases or "phase breakdown unavailable"))
        for unit, seconds in info.get("blame", []):
            line = Gtk.Box(spacing=8)
            name = Gtk.Label(label=unit.replace(".service", ""))
            name.set_xalign(0)
            name.set_hexpand(True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            time_chip = Gtk.Label(label=seconds)
            time_chip.get_style_context().add_class("chip")
            line.pack_start(name, True, True, 0)
            line.pack_start(time_chip, False, False, 0)
            self.boot_blame.pack_start(line, False, False, 0)
        self.boot_blame.show_all()

    def on_refresh_services(self, _btn=None):
        self.submit(services_backend.list_services, done=self._apply_services,
                    name="Listing services")
        self.submit(services_backend.boot_info, done=self._apply_boot,
                    name="Measuring boot time")

    def on_service_action(self, action):
        row = getattr(self, "selected_service_row", None)
        if row is None:
            self._notify("Select a service first.", "warning")
            return
        unit = row.unit
        if action in ("stop", "disable", "restart"):
            if not self._confirm("{} {}?".format(action.capitalize(), unit),
                                 "Stopped, restarted or disabled services may disable features "
                                 "you rely on (sound, network, desktop)."):
                return
        self.submit(services_backend.set_service_state, unit, action,
                    done=lambda _r: self.on_refresh_services(),
                    name="Changing service state")

    # ------------------------------------------------------------------
    # Drivers page
    # ------------------------------------------------------------------
    def _build_drivers_page(self):
        page = self._page(
            "drivers", "Drivers", "Drivers",
            "Devices detected by ubuntu-drivers with the driver packages that fit them. "
            "Recommended packages are pre-marked; installing applies after one "
            "administrator prompt.")

        toolbar = Gtk.Box(spacing=8)
        self.drivers_search = Gtk.SearchEntry()
        self.drivers_search.set_placeholder_text("Search detected devices")
        self.drivers_search.set_hexpand(True)
        self.drivers_search.connect("search-changed", self._on_drivers_search_changed)
        toolbar.pack_start(self.drivers_search, True, True, 0)
        toolbar.pack_start(self._button("Rescan", self.on_rescan_drivers,
                                        "Run ubuntu-drivers devices again",
                                        icon="view-refresh-symbolic"), False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.drivers_notice = self._hint("")
        self.drivers_notice.get_style_context().add_class("status-warning")
        self.drivers_notice.set_no_show_all(True)
        self.drivers_notice.hide()
        page.pack_start(self.drivers_notice, False, False, 0)

        self.drivers_empty = self._hint("No devices needing extra drivers were detected.")
        self.drivers_empty.set_no_show_all(True)
        self.drivers_empty.hide()
        self.drivers_list = Gtk.ListBox()
        self.drivers_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.drivers_list.set_activate_on_single_click(True)
        self.drivers_list.connect("row-activated", self._on_drivers_row_activated)
        self.drivers_list.set_filter_func(self._drivers_filter, None)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("list-surface")
        scroller.add(self.drivers_list)
        page.pack_start(self.drivers_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.drivers_counter = self._counter("No driver packages selected")
        self.drivers_counter.set_xalign(0)
        page.pack_start(self.drivers_counter, False, False, 0)
        self.drivers_buttons = {
            "install": self._button("Install Selected", self.on_install_drivers,
                                    "Install the selected recommended driver packages",
                                    primary=True),
            "auto": self._button("Auto Install (recommended)", self.on_autoinstall_drivers,
                                 "Let ubuntu-drivers install the recommended driver "
                                 "for every device"),
        }
        actions = self._flow(*self.drivers_buttons.values())
        actions.get_style_context().add_class("action-bar")
        page.pack_start(actions, False, False, 0)
        self._drivers_available = False
        self._update_drivers_counter()

    @staticmethod
    def _scan_drivers_worker(log=None):
        return drivers_backend.list_devices(log=log)

    def on_rescan_drivers(self, _btn=None):
        self.submit(self._scan_drivers_worker, done=self._fill_drivers_rows,
                    name="Scanning devices")

    def _drivers_filter(self, row, _data):
        query = self.drivers_search.get_text().strip().lower()
        if not hasattr(row, "search_text"):
            return True
        return not query or query in row.search_text

    def _on_drivers_search_changed(self, _entry):
        self.drivers_list.invalidate_filter()
        query = self.drivers_search.get_text().strip()
        visible = any(self._drivers_filter(row, None)
                      for row in self.drivers_list.get_children())
        if visible:
            self.drivers_empty.hide()
            return
        self.drivers_empty.set_text(
            "No devices match your search. Clear the search box to see them all."
            if query else
            "ubuntu-drivers is not installed; install ubuntu-drivers-common to use this page."
            if not self._drivers_available else
            "No devices needing extra drivers were detected.")
        self.drivers_empty.show()

    def _on_drivers_row_activated(self, _listbox, row):
        chk = getattr(row, "chk", None)
        if chk is not None and chk.get_sensitive():
            chk.set_active(not chk.get_active())

    def _fill_drivers_rows(self, result):
        if not isinstance(result, dict):
            return
        warnings = result.get("warnings") or []
        devices = result.get("devices") or []
        self._drivers_available = bool(result.get("available"))
        if warnings:
            self.drivers_notice.set_text("Driver detection reported problems. See Logs for details.")
            self.drivers_notice.set_tooltip_text("\n".join(warnings))
            self.drivers_notice.show()
        else:
            self.drivers_notice.hide()
        previously_selected = {
            row.key for row in self.drivers_list.get_children()
            if getattr(row, "chk", None) is not None and getattr(row, "key", None) is not None
            and row.chk.get_active()
        }
        for row in list(self.drivers_list.get_children()):
            self.drivers_list.remove(row)
        for device in devices:
            packages = device.get("packages") or []
            recommended = next((p for p in packages if p.get("recommended")), None)
            names = ", ".join(p["name"] for p in packages) or "no driver packages offered"
            row = Gtk.ListBoxRow()
            row.set_activatable(True)
            row.device = device
            row.key = device.get("modalias") or device.get("model", "")
            row.get_style_context().add_class("app-row")
            row.search_text = " ".join(
                [device.get("model", ""), device.get("vendor", ""), names]).lower()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            chk = Gtk.CheckButton()
            chk.set_sensitive(recommended is not None)
            chk.set_tooltip_text(
                "Select {}".format(recommended["name"]) if recommended else
                "ubuntu-drivers offers no installable package for this device")
            self._accessible_name(chk, "Install driver for " + device.get("model", "device"))
            chk.set_active(bool(recommended) and row.key in previously_selected)
            chk.connect("toggled", lambda _c: self._update_drivers_counter())
            line.pack_start(chk, False, False, 0)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            title = Gtk.Label(label=device.get("model") or device.get("modalias") or "Device")
            title.set_xalign(0)
            title.get_style_context().add_class("settings-title")
            text.pack_start(title, False, False, 0)
            subtitle = Gtk.Label(label=" | ".join(
                part for part in (device.get("vendor", ""), names) if part))
            subtitle.set_xalign(0)
            subtitle.set_ellipsize(Pango.EllipsizeMode.END)
            subtitle.get_style_context().add_class("settings-sub")
            text.pack_start(subtitle, False, False, 0)
            line.pack_start(text, True, True, 0)
            if recommended is not None:
                badge = Gtk.Label(label="recommended: " + recommended["name"])
                badge.get_style_context().add_class("badge")
                line.pack_start(badge, False, False, 0)
            row.add(line)
            row.chk = chk
            self.drivers_list.add(row)
        self.drivers_list.show_all()
        if not self._drivers_available:
            self.drivers_empty.set_text(
                "ubuntu-drivers is not installed; install ubuntu-drivers-common to use this page.")
            self.drivers_empty.show()
        elif not devices and not warnings:
            self.drivers_empty.set_text("No devices needing extra drivers were detected.")
            self.drivers_empty.show()
        elif devices:
            self.drivers_empty.hide()
        self._update_drivers_counter()

    def _selected_driver_packages(self):
        picks = []
        for row in self.drivers_list.get_children():
            chk = getattr(row, "chk", None)
            device = getattr(row, "device", None)
            if chk is None or device is None or not chk.get_active() or not chk.get_sensitive():
                continue
            recommended = next((p["name"] for p in device.get("packages", [])
                                if p.get("recommended")), None)
            if recommended:
                picks.append(recommended)
        return picks

    def _update_drivers_counter(self):
        count = len(self._selected_driver_packages())
        self.drivers_counter.set_text("{} selected".format(count) if count else "Nothing selected")
        if hasattr(self, "drivers_buttons"):
            self.drivers_buttons["install"].set_sensitive(not self._busy and count > 0)
            self.drivers_buttons["auto"].set_sensitive(
                not self._busy and getattr(self, "_drivers_available", False))

    def on_install_drivers(self, _btn):
        picks = self._selected_driver_packages()
        if not picks:
            self._notify("Tick at least one device with a recommended driver first.", "warning")
            return
        if not self._confirm("Install {} driver package(s)?".format(len(picks)),
                             "\n".join("• " + name for name in picks)):
            return
        self.submit(drivers_backend.install_driver, picks,
                    done=lambda _r: self.on_rescan_drivers(), name="Installing drivers")

    def on_autoinstall_drivers(self, _btn):
        if not self._confirm("Auto install recommended drivers?",
                             "ubuntu-drivers picks the recommended driver for every device "
                             "that needs one. This applies after one administrator prompt."):
            return
        self.submit(drivers_backend.autoinstall,
                    done=lambda _r: self.on_rescan_drivers(), name="Auto-installing drivers")

    # ------------------------------------------------------------------
    # Backup page
    # ------------------------------------------------------------------
    def _build_backup_page(self):
        page = self._page(
            "backup", "Backup & Restore", "Backup & Restore",
            "Create a Timeshift snapshot or save your personal settings. Config archives are "
            "checked before extraction so a bad archive cannot write outside ~/.config.",
            icon="drive-multidisk-symbolic")

        snap_frame, snap = self._frame("System snapshots (Timeshift)")
        snap.pack_start(self._flow(
            self._button("Create Snapshot", self.on_snapshot,
                         "Create a Timeshift snapshot (needs Timeshift installed)"),
            self._button("Open Timeshift", self.on_open_timeshift,
                         "Launch the Timeshift graphical interface"),
            self._button("Refresh List", self.on_refresh_snapshots,
                         "List saved Timeshift snapshots with administrator authorisation",
                         icon="view-refresh-symbolic"),
        ), False, False, 0)
        self.snapshot_listbox = Gtk.ListBox()
        self.snapshot_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.snapshot_empty = self._hint("Loading snapshots…")
        self.snapshot_empty.set_no_show_all(True)
        snap.pack_start(self.snapshot_empty, False, False, 0)
        snapshot_scroller = Gtk.ScrolledWindow()
        snapshot_scroller.set_min_content_height(130)
        snapshot_scroller.add(self.snapshot_listbox)
        snap.pack_start(snapshot_scroller, True, True, 0)
        snap.pack_start(self._hint("Timeshift is a separate package. Refresh List may ask for "
                                   "administrator access; install it first if missing."), False, False, 0)
        page.pack_start(snap_frame, True, True, 0)

        config_frame, config = self._frame("Personal settings (~/.config)")
        config.pack_start(self._flow(
            self._button("Export Settings…", self.on_export_config,
                         "Save ~/.config to a .tar.xz archive", primary=True,
                         icon="document-save-symbolic"),
            self._button("Import Settings…", self.on_import_config,
                         "Restore ~/.config from an archive"),
        ), False, False, 0)
        config.pack_start(self._hint(
            "Import overwrites matching files in ~/.config. Export first if you are unsure."),
            False, False, 0)
        page.pack_start(config_frame, False, False, 0)

    def on_refresh_snapshots(self, _btn=None):
        if utils.is_simulate():
            self.log_buf.append("[simulate] would request administrator access to list Timeshift snapshots\n")
            self._notify("Snapshot list was not refreshed in Simulate mode.", "info")
            return
        self.submit(backup_backend.list_snapshots, True, done=self._apply_snapshots,
                    name="Listing snapshots")

    def _apply_snapshots(self, snapshots):
        for row in list(self.snapshot_listbox.get_children()):
            self.snapshot_listbox.remove(row)
        if not isinstance(snapshots, list):
            self.snapshot_empty.set_text(
                "Snapshots unavailable. Timeshift may be missing or require administrator access; "
                "use Refresh List, see Logs, or open Timeshift.")
            self.snapshot_empty.show()
            return
        if snapshots:
            self.snapshot_empty.hide()
        else:
            self.snapshot_empty.set_text("No snapshots found.")
            self.snapshot_empty.show()
        for item in snapshots:
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("snapshot-row")
            line = Gtk.Box(spacing=10)
            title = Gtk.Label(label=item.get("name", ""))
            title.set_xalign(0)
            title.set_hexpand(True)
            line.pack_start(title, True, True, 0)
            if item.get("tags"):
                tags = Gtk.Label(label=item["tags"])
                tags.get_style_context().add_class("badge")
                line.pack_start(tags, False, False, 0)
            if item.get("date"):
                when = Gtk.Label(label=item["date"])
                when.get_style_context().add_class("hint-label")
                line.pack_start(when, False, False, 0)
            row.add(line)
            self.snapshot_listbox.add(row)
        self.snapshot_listbox.show_all()


    def on_snapshot(self, _btn):
        def finished(result):
            if isinstance(result, utils.Outcome) and result.ok and not utils.is_simulate():
                self._notify("Snapshot requested. Use Refresh List to update the list.", "info")
        # Never trigger a second, automatic polkit prompt after creating one.
        self.submit(backup_backend.timeshift_snapshot, done=finished, name="Creating snapshot")

    def on_open_timeshift(self, _btn):
        self.submit(backup_backend.open_timeshift_gui, name="Opening Timeshift")

    def _save_dialog(self, title, name):
        dialog = Gtk.FileChooserDialog(title=title, parent=self,
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_name(name)
        dialog.set_do_overwrite_confirmation(True)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        return path if response == Gtk.ResponseType.OK else None

    def _open_dialog(self, title):
        dialog = Gtk.FileChooserDialog(title=title, parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        return path if response == Gtk.ResponseType.OK else None

    def on_export_config(self, _btn):
        path = self._save_dialog("Save settings archive", "preen-config-backup.tar.xz")
        if path:
            self.submit(backup_backend.export_configs, path, name="Exporting settings")

    def on_import_config(self, _btn):
        path = self._open_dialog("Open settings archive")
        if path:
            # Reading and decompressing large archives can take a long time;
            # inspect in the FIFO worker, then ask for confirmation on GTK.
            self.submit(backup_backend.inspect_archive, path,
                        done=lambda result: self._confirm_config_import(path, result),
                        name="Inspecting settings archive")

    def _confirm_config_import(self, path, result):
        if not isinstance(result, tuple) or len(result) != 2:
            return  # the worker has already reported its error
        safe_count, unsafe = result
        if unsafe:
            self._notify("Cannot import: unsafe archive or destination. Nothing was restored. "
                         + ", ".join(unsafe[:5]), "error")
            return
        if safe_count == 0:
            self._notify("Cannot import: archive is empty or unreadable.", "error")
            return
        message = "This overwrites files in ~/.config with {} item(s) from the archive.".format(safe_count)
        if self._confirm("Restore settings?", message):
            # The backend revalidates after confirmation in case either the
            # archive or destination changed while the dialog was open.
            self.submit(backup_backend.import_configs, path, name="Restoring settings")

    # ------------------------------------------------------------------
    # Logs page
    # ------------------------------------------------------------------
    def _build_logs_page(self):
        page = self._page(
            "logs", "Logs", "Logs",
            "Review commands, simulation previews and diagnostic messages. "
            "The complete log can be saved for support.",
            icon="document-open-recent-symbolic")

        tools = Gtk.Box(spacing=8)
        save = self._button("Save Log…", self.on_save_log,
                            "Save the complete log, including filtered lines",
                            icon="document-save-symbolic")
        clear = self._button("Clear Log", self.on_clear_log,
                             "Clear the complete log", icon="edit-clear-symbolic")
        tools.pack_start(save, False, False, 0)
        tools.pack_start(clear, False, False, 0)
        scroll_switch = Gtk.Switch()
        self._accessible_name(scroll_switch, "Auto-scroll log")
        scroll_switch.set_active(True)
        scroll_switch.set_tooltip_text("Automatically scroll to the newest line")
        scroll_switch.connect("notify::active", self.on_toggle_auto_scroll)
        tools.pack_start(Gtk.Label(label="Auto-scroll"), False, False, 0)
        tools.pack_start(scroll_switch, False, False, 0)
        self.log_filter = Gtk.SearchEntry()
        self.log_filter.set_placeholder_text("Filter log…")
        self.log_filter.set_hexpand(True)
        self.log_filter.set_tooltip_text("Only show lines containing this text")
        self.log_filter.connect("search-changed", self.on_log_filter_changed)
        tools.pack_end(self.log_filter, True, True, 0)
        page.pack_start(tools, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.get_style_context().add_class("log-surface")
        scroller.add(self.log_view)
        page.pack_start(scroller, True, True, 0)

    def on_log_filter_changed(self, entry):
        self.log_buf.set_filter(entry.get_text())

    def on_toggle_auto_scroll(self, switch, _param):
        self.log_buf.auto_scroll = switch.get_active()

    def on_clear_log(self, _btn):
        self.log_buf.clear()

    def on_save_log(self, _btn):
        path = self._save_dialog("Save log", "preen.log")
        if not path:
            return
        if self.log_buf.save(path):
            self._notice("Log saved to " + path)
        else:
            self._notify("Could not write " + path, "error")

    # ------------------------------------------------------------------
    # Header actions
    # ------------------------------------------------------------------
    def on_toggle_simulate(self, switch, _param):
        enabled = switch.get_active()
        utils.set_simulate(enabled)
        if utils.is_simulate() != enabled:
            # An environment-forced dry run must never appear switched off.
            switch.set_active(True)
            return
        self._update_sim_banner()
        self.log_buf.append("[simulate] {}\n".format("ON" if enabled else "OFF"))
        self.status_label.set_text("Simulate ON, no changes will be made" if enabled else "Ready")
        if enabled:
            self._notify("Simulate is ON. Actions are previewed in Logs only.", "info")

    def on_preferences(self, _btn):
        dialog = Gtk.Dialog(title="Preferences", parent=self, flags=0,
                            use_header_bar=True)
        dialog.set_default_size(460, 400)
        dialog.set_border_width(12)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(10)

        def add_switch(label, tooltip, active):
            line = Gtk.Box(spacing=8)
            text = Gtk.Label(label=label)
            text.set_xalign(0)
            text.set_hexpand(True)
            text.set_tooltip_text(tooltip)
            switch = Gtk.Switch()
            self._accessible_name(switch, label)
            switch.set_tooltip_text(tooltip)
            switch.set_active(active)
            line.pack_start(text, True, True, 0)
            line.pack_start(switch, False, False, 0)
            content.pack_start(line, False, False, 0)
            return switch

        source_box = Gtk.Box(spacing=8)
        source_box.pack_start(Gtk.Label(label="Preferred package source:"), False, False, 0)
        source_combo = Gtk.ComboBoxText()
        for text in ("Flatpak", "APT"):
            source_combo.append_text(text)
        source_combo.set_active(0 if self.settings.get("default_source") == "flatpak" else 1)
        source_box.pack_start(source_combo, False, False, 0)
        content.pack_start(source_box, False, False, 0)

        refresh_box = Gtk.Box(spacing=8)
        refresh_box.pack_start(Gtk.Label(label="Dashboard auto-refresh:"), False, False, 0)
        refresh_combo = Gtk.ComboBoxText()
        for text in ("Off", "Every 10 s", "Every 15 s", "Every 30 s", "Every 60 s"):
            refresh_combo.append_text(text)
        refresh_values = [0, 10, 15, 30, 60]
        current_refresh = self.settings.get("auto_refresh_seconds", 15)
        refresh_combo.set_active(refresh_values.index(current_refresh)
                                 if current_refresh in refresh_values else 2)
        refresh_box.pack_start(refresh_combo, False, False, 0)
        content.pack_start(refresh_box, False, False, 0)

        page_box = Gtk.Box(spacing=8)
        page_box.pack_start(Gtk.Label(label="Page shown on startup:"), False, False, 0)
        page_combo = Gtk.ComboBoxText()
        startup_pages = [page for _section, pages in self.SIDEBAR_SECTIONS for page in pages]
        for _name, label, _icon, _tile in startup_pages:
            page_combo.append_text(label)
        current_page = self.settings.get("page_on_startup", "dashboard")
        page_ids = [name for name, _l, _i, _t in startup_pages]
        page_combo.set_active(page_ids.index(current_page) if current_page in page_ids else 0)
        page_box.pack_start(page_combo, False, False, 0)
        content.pack_start(page_box, False, False, 0)

        sim_switch = add_switch("Start in Simulate mode",
                                "Safe default: preview all actions until you switch it off",
                                bool(self.settings.get("simulate_on_startup")))
        confirm_switch = add_switch("Confirm full package updates",
                                    "Cleanup, uninstall and restore always require confirmation",
                                    bool(self.settings.get("confirm_destructive", True)))
        warn_switch = add_switch("Show dependency warnings",
                                 "Warn at startup when flatpak, polkit or gsettings is missing",
                                 bool(self.settings.get("show_dependency_warnings", True)))
        content.pack_start(self._hint(
            "Source and safety options apply immediately. Startup and refresh "
            "options apply after a restart."), False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            startup_index = max(0, page_combo.get_active())
            values = {
                "default_source": "apt" if source_combo.get_active() == 1 else "flatpak",
                "auto_refresh_seconds": refresh_values[max(0, refresh_combo.get_active())],
                "page_on_startup": page_ids[startup_index],
                "simulate_on_startup": sim_switch.get_active(),
                "confirm_destructive": confirm_switch.get_active(),
                "show_dependency_warnings": warn_switch.get_active(),
            }
            if settings_backend.update(values):
                self.settings = settings_backend.load()
                self.install_source.set_active(0 if values["default_source"] == "flatpak" else 1)
                self._notify("Preferences saved. Startup and refresh options apply after a restart.",
                             "info")
            else:
                self._notify("Could not save preferences, check permissions on ~/.config.", "error")
        dialog.destroy()

    def on_help(self, _btn):
        self._show_dialog(
            "Quick start",
            "1. Turn on Simulate (top right) to preview actions safely.\n"
            "2. Dashboard shows live CPU, memory, disk and swap usage and which tools are available.\n"
            "3. Install Apps: search, tick (or click a row), then Install Selected. APT and Flatpak both work.\n"
            "4. AppImages: drag a .AppImage onto the window, or install downloads from the AppImages page. "
            "Installing again over an installed app updates it.\n"
            "5. Deep Clean: scan first, review the sizes, then clean only what you ticked.\n"
            "6. Optimize System: only the settings you changed are applied.\n"
            "7. Services: inspect boot time and start, stop or restart systemd units.\n"
            "8. Logs shows every command and its result, with a filter and Save Log for support.\n\n"
            "Keyboard: F5 refreshes the visible page, Ctrl+F jumps to its search box, "
            "Ctrl+A selects all on list pages, Escape dismisses a notice.\n\n"
            "Full guide: docs/USER_GUIDE.md in the repository.",
            Gtk.MessageType.INFO)

    def on_about(self, _btn):
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name(APP_NAME)
        dialog.set_version("v" + __version__)
        dialog.set_comments("System setup, deep cleaning and tuning for Linux.")
        dialog.set_website("https://github.com/mdadeel/Preen")
        dialog.set_website_label("Project on GitHub")
        dialog.set_license("MIT")
        dialog.set_authors(["Preen contributors"])
        try:
            logo = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ASSETS_DIR / "preen.png"), 64, 64, True)
            dialog.set_logo(logo)
        except Exception:
            dialog.set_logo_icon_name("utilities-system-monitor")
        dialog.run()
        dialog.destroy()


class PreenApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
