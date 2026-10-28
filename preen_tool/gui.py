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

import threading
import traceback
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")  # systems shipping Gdk 4.0 otherwise load it by default and clash with Gtk 3
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .backend import (  # noqa: E402
    apps as apps_backend,
    backup as backup_backend,
    dashboard as dash_backend,
    deepclean as deepclean_backend,
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

# Small, purely cosmetic stylesheet. Wrapped in try/except at load time:
# a missing theme feature must never prevent the app from starting.
# Every colour is a named theme colour (or an alpha of one), so the whole UI
# follows the system light/dark theme, except the sidebar tiles, which use
# fixed macOS-system-palette accents that stay vibrant in both modes.
# @accent_color is not defined in GTK 3 themes; @theme_selected_bg_color
# plays that role.
_CSS = b"""
/* ============================================================
   Preen GTK theme, macOS System Settings (Sequoia) inspired.
   Flat fills only, no gradients. Light and dark both work by
   riding the Adwaita @theme_* tokens; the accent is the macOS
   system blue, which reads correctly in both schemes.
   ============================================================ */
@define-color mac_blue #0a84ff;
@define-color mac_blue_press #0066d6;
@define-color mac_green #30d158;
@define-color mac_purple #bf5af2;
@define-color mac_orange #ff9f0a;
@define-color mac_pink #ff375f;
@define-color mac_teal #64d2ff;
@define-color mac_slate #8e939c;
@define-color hairline alpha(@theme_fg_color, 0.09);
@define-color soft_fill alpha(@theme_fg_color, 0.06);

* {
    font-family: -apple-system, "SF Pro Text", "Inter", "Segoe UI",
                 "Cantarell", "Ubuntu", sans-serif;
}

/* ----- Window: flat neutral canvas, white grouped cards sit on it ----- */
window {
    background-color: @theme_bg_color;
}

/* ----- Flat header bar ----- */
headerbar {
    background-image: none;
    background-color: @theme_bg_color;
    border-bottom: 1px solid @hairline;
    box-shadow: none;
    min-height: 44px;
    padding: 4px 8px;
}
headerbar button:not(:hover):not(:active):not(:checked) {
    background-image: none;
    background-color: transparent;
    border-color: transparent;
    box-shadow: none;
}
headerbar entry, headerbar > box entry { border-radius: 999px; }

/* ----- Simulate mode pill ----- */
.simulate-banner {
    background-color: alpha(@warning_color, 0.22);
    color: @theme_fg_color;
    border-radius: 999px;
    padding: 3px 12px;
    font-weight: 600;
    font-size: 0.9em;
    letter-spacing: 0.03em;
}

/* ----- Bottom status bar ----- */
actionbar {
    background-image: none;
    background-color: @theme_bg_color;
    border-top: 1px solid @hairline;
    padding: 4px 12px;
}

/* ----- Sidebar: macOS System Settings ----- */
.sidebar {
    background-color: alpha(@theme_base_color, 0.5);
    border-right: 1px solid @hairline;
    padding: 10px 10px 12px 10px;
    min-width: 232px;
}
.sidebar .sidebar-search {
    margin: 4px 6px 10px 6px;
    border-radius: 999px;
    min-height: 30px;
}
.sidebar-section {
    color: alpha(@theme_fg_color, 0.48);
    font-size: 0.76em;
    font-weight: 700;
    letter-spacing: 0.07em;
    padding: 14px 12px 5px 12px;
}
.page-row {
    border-radius: 8px;
    padding: 5px 10px;
    margin: 1px 2px;
    min-height: 34px;
}
.page-row:hover:not(:selected) {
    background-color: @soft_fill;
}
.page-row:selected {
    background-color: @mac_blue;
    color: #ffffff;
}
.page-row:selected label { color: #ffffff; font-weight: 700; }

/* Coloured symbol tiles, the macOS sidebar icon set */
.tile {
    border-radius: 7px;
    min-width: 28px;
    min-height: 28px;
}
.tile image {
    color: #ffffff;
    -gtk-icon-shadow: none;
}
.tile-blue   { background-image: none; background-color: @mac_blue; }
.tile-green  { background-image: none; background-color: @mac_green; }
.tile-purple { background-image: none; background-color: @mac_purple; }
.tile-orange { background-image: none; background-color: @mac_orange; }
.tile-pink   { background-image: none; background-color: @mac_pink; }
.tile-teal   { background-image: none; background-color: @mac_teal; }
.tile-slate  { background-image: none; background-color: @mac_slate; }

/* ----- Typography ----- */
.page-title { font-size: 1.5em; font-weight: 700; letter-spacing: -0.02em; }
.page-subtitle { color: alpha(@theme_fg_color, 0.6); font-size: 0.95em; }
.card-title { font-size: 1.02em; font-weight: 700; letter-spacing: -0.01em; }
.hint-label, .dim-label { color: alpha(@theme_fg_color, 0.55); font-size: 0.9em; }
.counter-label { color: alpha(@theme_fg_color, 0.55); font-size: 0.9em; }
.settings-title { font-weight: 600; }
.settings-sub { color: alpha(@theme_fg_color, 0.55); font-size: 0.88em; }

/* ----- Grouped inset cards ----- */
.card {
    background-color: @theme_base_color;
    border: 1px solid @hairline;
    border-radius: 12px;
    padding: 18px 20px;
}

/* Inset setting rows: hairline separators like System Settings */
.settings-row {
    min-height: 40px;
    padding: 7px 2px;
    border-bottom: 1px solid @hairline;
}
.settings-row:last-child { border-bottom: none; }
.settings-row + .dim-label { margin-top: 10px; }
.settings-row button.flat { padding-left: 0; }

/* ----- Dashboard hero + stat cards ----- */
.hero-card {
    background-color: alpha(@mac_blue, 0.09);
    border: 1px solid alpha(@mac_blue, 0.25);
    border-radius: 14px;
    padding: 20px;
}
.hero-os { font-size: 1.3em; font-weight: 700; letter-spacing: -0.01em; }
.hero-meta { color: alpha(@theme_fg_color, 0.6); }
.stat-card {
    background-color: @theme_base_color;
    border: 1px solid @hairline;
    border-radius: 12px;
    padding: 14px 16px;
}
.stat-value { font-size: 1.35em; font-weight: 700; letter-spacing: -0.01em; }
.stat-name { color: alpha(@theme_fg_color, 0.55); font-weight: 600; }
.stat-card progressbar trough {
    background-color: alpha(@theme_fg_color, 0.12);
    border: none;
    border-radius: 999px;
    min-height: 6px;
}
.stat-card progressbar progress {
    border-radius: 999px;
    min-height: 6px;
    border: none;
}
.stat-cpu progressbar progress  { background-color: @mac_blue; }
.stat-mem progressbar progress  { background-color: @mac_purple; }
.stat-disk progressbar progress { background-color: @mac_green; }
.stat-swap progressbar progress { background-color: @mac_teal; }

/* ----- Badges & chips ----- */
.chip {
    background-color: @soft_fill;
    border-radius: 999px;
    padding: 3px 11px;
    font-size: 0.9em;
}
.chip-ok { background-color: alpha(@success_color, 0.25); }
.chip-bad { background-color: alpha(@error_color, 0.2); }
.chip-muted { background-color: @soft_fill; color: alpha(@theme_fg_color, 0.7); }
.badge {
    background-color: alpha(@mac_blue, 0.15);
    border-radius: 999px;
    padding: 2px 9px;
    font-size: 0.85em;
}
.badge-ok { background-color: alpha(@success_color, 0.25); }
.badge-bad { background-color: alpha(@error_color, 0.2); }

/* ----- macOS capsule segmented control ----- */
.segmented {
    background-color: alpha(@theme_fg_color, 0.09);
    border-radius: 999px;
    padding: 2px;
}
.segmented button {
    border: none;
    border-radius: 999px;
    background: transparent;
    padding: 5px 16px;
    font-weight: 600;
    box-shadow: none;
}
.segmented button:checked,
.segmented button:active {
    background-color: @theme_base_color;
    color: @theme_fg_color;
    box-shadow: 0 1px 3px alpha(rgb(0, 0, 0), 0.18);
}

/* ----- Buttons ----- */
button {
    border-radius: 8px;
    padding: 6px 14px;
}
button.suggested-action {
    background-image: none;
    background-color: @mac_blue;
    color: #ffffff;
    border: none;
    border-radius: 999px;
    padding: 7px 20px;
    font-weight: 600;
}
button.suggested-action:hover { background-color: shade(@mac_blue, 1.12); }
button.suggested-action:active { background-color: @mac_blue_press; }
button.destructive-action {
    background-image: none;
    background-color: @error_color;
    color: #ffffff;
    border: none;
    border-radius: 999px;
    padding: 7px 20px;
    font-weight: 600;
}
button.destructive-action:hover { background-color: shade(@error_color, 1.1); }
button.flat { border-radius: 8px; }
button.flat:hover { background-color: @soft_fill; }

/* ----- Entries and search fields ----- */
entry, searchbar entry {
    border-radius: 9px;
    padding: 6px 10px;
    border: 1px solid @hairline;
    background-color: @theme_base_color;
}
entry:focus { border-color: @mac_blue; }

/* ----- Dropdowns ----- */
combobox box, combobox > box > button.combo { border-radius: 9px; }
button.combo {
    border-radius: 9px;
    padding: 6px 12px;
    min-height: 32px;
}

/* ----- macOS capsule switches ----- */
switch {
    border: none;
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.2);
    min-width: 46px;
    min-height: 27px;
    padding: 0;
    background-image: none;
}
switch slider {
    border-radius: 50%;
    background-color: #ffffff;
    min-width: 23px;
    min-height: 23px;
    margin: 2px;
    border: none;
    box-shadow: 0 1px 3px alpha(rgb(0, 0, 0), 0.3);
}
switch:checked { background-color: @mac_blue; }
switch:checked slider { background-color: #ffffff; }

/* ----- Sliders: thin rounded track, round knob ----- */
scale { padding: 6px 0; }
scale trough {
    min-height: 4px;
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.18);
}
scale highlight {
    border-radius: 999px;
    background-color: @mac_blue;
}
scale slider {
    min-width: 18px;
    min-height: 18px;
    border-radius: 50%;
    background-color: #ffffff;
    border: 1px solid alpha(rgb(0, 0, 0), 0.12);
    box-shadow: 0 1px 3px alpha(rgb(0, 0, 0), 0.25);
}

/* ----- Checkboxes and radios: rounded squircle, blue when on ----- */
check, check row check, radio {
    border-radius: 5px;
    border: 1.5px solid alpha(@theme_fg_color, 0.35);
    background-color: @theme_base_color;
    min-width: 18px;
    min-height: 18px;
}
check:checked, radio:checked {
    background-color: @mac_blue;
    border-color: @mac_blue;
}
radio { border-radius: 50%; }

/* ----- Separators and scrollbars ----- */
separator { background-color: @hairline; }
scrollbar { background: transparent; border: none; }
scrollbar slider {
    border-radius: 999px;
    min-width: 8px;
    min-height: 8px;
    background-color: alpha(@theme_fg_color, 0.25);
    border: none;
}
scrollbar trough { background: transparent; border: none; }

/* ----- Log viewer ----- */
textview {
    border-radius: 10px;
    padding: 4px;
}
textview text {
    background-color: @theme_base_color;
}

/* ----- Banners ----- */
infobar { border-radius: 12px; }
.info-banner { background-color: alpha(@mac_blue, 0.12); }
.warning-banner { background-color: alpha(@warning_color, 0.18); }
.error-banner { background-color: alpha(@error_color, 0.16); }

/* ----- Menus and dialogs ----- */
popover { border-radius: 12px; }
popover modelbutton {
    border-radius: 8px;
    padding: 8px 14px;
    margin: 2px 4px;
}
dialog { border-radius: 16px; }
dialog > box { padding: 10px; }
dialog button { border-radius: 999px; padding: 7px 18px; }

/* ----- Step numbers and list rows ----- */
.step-number {
    background-color: @mac_blue;
    color: #ffffff;
    border-radius: 999px;
    min-width: 24px;
    min-height: 24px;
    padding: 2px 4px;
    font-weight: 700;
}
.app-row { padding: 9px 10px; border-bottom: 1px solid @hairline; }
.app-row:last-child { border-bottom: none; }
.app-row:hover { background-color: @soft_fill; }
.list-header { padding-top: 14px; padding-bottom: 4px; }
.snapshot-row { padding: 7px 10px; border-bottom: 1px solid @hairline; }
.snapshot-row:last-child { border-bottom: none; }
.snapshot-row:hover { background-color: @soft_fill; }
"""


def _escape_markup(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class LogBuffer:
    """Thread-safe append-only log with an in-memory copy for saving."""

    def __init__(self, textbuffer: Gtk.TextBuffer, textview: Gtk.TextView):
        self.buf = textbuffer
        self.view = textview
        self.lines = []
        self.auto_scroll = True
        self.filter_text = ""
        self._lock = threading.Lock()

    def append(self, text: str):
        text = str(text)
        with self._lock:
            self.lines.append(text)
            if len(self.lines) > MAX_LOG_LINES:
                self.lines = self.lines[-MAX_LOG_LINES:]
        GLib.idle_add(self._append, text)

    def _append(self, text: str):
        # While a filter is active the view is rebuilt on demand, so only
        # insert lines that match the current filter.
        if not self.filter_text or self.filter_text in text.lower():
            end = self.buf.get_end_iter()
            self.buf.insert(end, text)
            if self.auto_scroll:
                mark = self.buf.create_mark(None, self.buf.get_end_iter(), True)
                self.view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
                self.buf.delete_mark(mark)
        if self.buf.get_line_count() > MAX_LOG_LINES:
            start = self.buf.get_start_iter()
            cutoff = self.buf.get_iter_at_line(self.buf.get_line_count() - MAX_LOG_LINES)
            self.buf.delete(start, cutoff)
        return False

    def set_filter(self, text: str):
        """Keep every line in memory but show only those containing *text*."""
        self.filter_text = (text or "").strip().lower()
        GLib.idle_add(self._rebuild)

    def _rebuild(self):
        self.buf.set_text("")
        if not self.filter_text:
            end = self.buf.get_end_iter()
            for line in self.lines:
                self.buf.insert(end, line)
        else:
            end = self.buf.get_end_iter()
            for line in self.lines:
                if self.filter_text in line.lower():
                    self.buf.insert(end, line)
        if self.auto_scroll:
            mark = self.buf.create_mark(None, self.buf.get_end_iter(), True)
            self.view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
            self.buf.delete_mark(mark)
        return False

    def clear(self):
        with self._lock:
            self.lines.clear()
        GLib.idle_add(self.buf.set_text, "")

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
        self.set_default_size(1140, 780)
        window_position = getattr(getattr(Gtk, "WindowPosition", None), "CENTER", None)
        if window_position is not None:
            self.set_position(window_position)
        self._busy = False
        self._busy_lock = threading.Lock()
        # FIFO task queue. The old runner rejected every submit() while a
        # task was running, which silently dropped the startup reads (boot
        # info, service list, cleanable scan and preferences never loaded).
        self._queue = deque()
        self.action_widgets = []
        self.app_rows = {}
        self.clean_checkbuttons = {}
        self.selected_service_row = None
        self.baseline = {
            "animations_off": False, "swap": False, "zram": False,
            "power": "balanced", "theme": "light", "round": False,
        }
        self.settings = settings_backend.load()
        if self.settings.get("simulate_on_startup"):
            utils.set_simulate(True)

        self._install_css()

        # ----- Header bar (compact: icon + name, actions tucked into a menu) -----
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)

        title_box = Gtk.Box(spacing=8)
        title_box.pack_start(self._icon("utilities-system-monitor", 18), False, False, 0)
        app_title = Gtk.Label()
        app_title.set_markup("<b>{}</b>".format(APP_NAME))
        app_title.set_xalign(0)
        title_box.pack_start(app_title, False, False, 0)
        title_box.set_tooltip_text("System setup for Linux")
        header.set_custom_title(title_box)

        # Spinner and status label are created here but live in the bottom
        # status bar, the header stays clean.
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.set_xalign(0)

        header.pack_end(self._build_menu_button())

        sim_box = Gtk.Box(spacing=6)
        sim_box.set_tooltip_text("Dry-run: preview every action without changing the system")
        self.sim_switch = Gtk.Switch()
        self.sim_switch.set_tooltip_text("Dry-run: preview every action without changing the system")
        # Set the saved state *before* connecting, so startup does not emit a
        # spurious signal and print a duplicate "Simulate is ON" notice.
        self.sim_switch.set_active(utils.is_simulate())
        self.sim_switch.connect("notify::active", self.on_toggle_simulate)
        sim_box.pack_start(Gtk.Label(label="Simulate"), False, False, 0)
        sim_box.pack_start(self.sim_switch, False, False, 0)
        header.pack_end(sim_box)
        self.set_titlebar(header)

        # ----- Global banners -----
        self.banner = Gtk.InfoBar()
        self.banner_label = Gtk.Label(label="")
        self.banner_label.set_line_wrap(True)
        self.banner_label.set_xalign(0)
        self.banner.get_content_area().pack_start(self.banner_label, True, True, 0)
        self.banner.add_button("Dismiss", Gtk.ResponseType.CLOSE)
        self.banner.connect("response", self._dismiss_banner)
        self.banner.set_no_show_all(True)
        self.banner.hide()

        self.sim_banner = Gtk.Label(
            label="SIMULATE MODE: commands are previewed in Logs; nothing will be changed.")
        self.sim_banner.set_name("simulate-banner")
        self.sim_banner.get_style_context().add_class("simulate-banner")
        self.sim_banner.set_no_show_all(True)

        # ----- Main layout -----
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=180)
        self.stack.set_transition_duration(180)
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.sidebar_list.connect("row_selected", self._on_sidebar_row_selected)
        self.sidebar_list.set_filter_func(self._sidebar_filter)
        self._sidebar_query = ""
        self.stack.connect("notify::visible-child-name", self._on_stack_page_changed)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.get_style_context().add_class("sidebar")

        # macOS-style search pinned above the sidebar sections. It lives
        # outside the ListBox, so row/header counts never change while
        # filtering toggles row visibility instead.
        self.sidebar_search = Gtk.SearchEntry()
        self.sidebar_search.set_placeholder_text("Search")
        self.sidebar_search.get_style_context().add_class("sidebar-search")
        self.sidebar_search.set_tooltip_text("Find a settings page")
        self.sidebar_search.connect("search-changed", self._on_sidebar_search_changed)
        sidebar.pack_start(self.sidebar_search, False, False, 0)
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.add(self.sidebar_list)
        sidebar.pack_start(sidebar_scroll, True, True, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        panes.pack_start(sidebar, False, False, 0)
        panes.pack_start(self.stack, True, True, 0)
        body.pack_start(panes, True, True, 0)

        # ----- Bottom dock: alerts slide up above a slim status bar -----
        footer = Gtk.ActionBar()
        status_box = Gtk.Box(spacing=8)
        status_box.pack_start(self.spinner, False, False, 0)
        status_box.pack_start(self.status_label, False, False, 0)
        footer.pack_start(status_box)
        footer.pack_end(self.sim_banner)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bottom.pack_start(self.banner, False, False, 0)
        bottom.pack_start(footer, False, False, 0)
        body.pack_start(bottom, False, False, 0)
        self.add(body)

        # ----- Shared log view -----
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buf = LogBuffer(self.log_view.get_buffer(), self.log_view)

        # ----- Pages (Dashboard first: it is the landing page) -----
        self._build_dashboard_page()
        self._build_install_page()
        self._build_manage_page()
        self._build_optimize_page()
        self._build_customize_page()
        self._build_deepclean_page()
        self._build_services_page()
        self._build_backup_page()
        self._build_logs_page()
        self._populate_sidebar()

        # Saved preferences were applied while building the widgets, so no
        # "changed" signal can start a task before the startup chain does.
        self._update_sim_banner()

        self.show_all()
        self.stack.set_visible_child_name(self.settings.get("page_on_startup", "dashboard"))
        self.log_buf.append("[info] {} {} ready. Simulate is {}.\n".format(
            APP_NAME, __version__, "ON" if utils.is_simulate() else "OFF"))
        self._start_initial_tasks()

    # ------------------------------------------------------------------
    # Small UI factories
    # ------------------------------------------------------------------
    def _install_css(self):
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(_CSS)
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception:  # cosmetics only
            pass

    def _header_button(self, label, callback, tooltip):
        button = Gtk.Button(label=label)
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

    @staticmethod
    def _icon(name, size=16):
        # Gtk.IconSize.MENU == 1; a literal keeps the fake-GTK tests happy,
        # which cannot resolve Gtk.IconSize attribute chains.
        try:
            icon = Gtk.Image.new_from_icon_name(name, 1)
            icon.set_pixel_size(size)
            return icon
        except Exception:
            return Gtk.Label(label="•")

    def _segmented(self, options, active_index=0, tooltip=None):
        """A macOS-style segmented control.

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

        def select(index, _btn=None):
            for pos, button in enumerate(buttons):
                button.set_active(pos == index)

        for index, text in enumerate(options):
            button = Gtk.ToggleButton(label=text)
            button.set_active(index == active_index)
            button.connect("clicked", lambda _b, i=index: select(i))
            buttons.append(button)
            box.pack_start(button, False, False, 0)

        def get_active_text():
            for index, button in enumerate(buttons):
                if button.get_active():
                    return options[index]
            return options[0]

        box.get_active_text = get_active_text
        box.set_active = select
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
                icon=None, flat=False):
        if icon:
            button = Gtk.Button()
            inner = Gtk.Box(spacing=7)
            inner.pack_start(self._icon(icon), False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            button.add(inner)
        else:
            button = Gtk.Button(label=label)
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
        box.set_border_width(22)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title_row = Gtk.Box(spacing=10)
        if icon:
            title_row.pack_start(self._icon(icon, 20), False, False, 0)
        heading = Gtk.Label()
        heading.set_markup("<b>{}</b>".format(_escape_markup(title)))
        heading.set_xalign(0)
        heading.get_style_context().add_class("page-title")
        title_row.pack_start(heading, False, False, 0)
        header.pack_start(title_row, False, False, 0)
        sub = Gtk.Label(label=subtitle)
        sub.set_xalign(0)
        sub.set_line_wrap(True)
        sub.get_style_context().add_class("page-subtitle")
        header.pack_start(sub, False, False, 0)
        box.pack_start(header, False, False, 0)
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
        card.pack_start(inner, False, False, 0)
        return card, inner

    def _toggle_row(self, title, subtitle=None, tooltip=None):
        """A macOS-style grouped row: title (and sub-caption) left, switch right.

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
        if tooltip:
            switch.set_tooltip_text(tooltip)
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

    # ------------------------------------------------------------------
    # Sidebar navigation
    # ------------------------------------------------------------------
    # Grouped the way macOS System Settings groups its sidebar.
    SIDEBAR_SECTIONS = [
        ("Overview", [
            ("dashboard", "Dashboard", "computer-symbolic", "tile-blue"),
        ]),
        ("Software", [
            ("install", "Install Apps", "system-software-install-symbolic", "tile-green"),
            ("manage", "Manage Apps", "application-x-executable-symbolic", "tile-purple"),
        ]),
        ("System", [
            ("deepclean", "Deep Clean", "user-trash-symbolic", "tile-orange"),
            ("optimize", "Optimize System", "speedometer-symbolic", "tile-pink"),
            ("services", "Services", "system-run-symbolic", "tile-teal"),
            ("backup", "Backup & Restore", "drive-multidisk-symbolic", "tile-purple"),
        ]),
        ("Personal", [
            ("customize", "Customize Look", "preferences-desktop-appearance", "tile-blue"),
            ("logs", "Logs", "document-open-recent-symbolic", "tile-slate"),
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

            for name, label, icon, tile_class in pages:
                row = Gtk.ListBoxRow()
                row.page_name = name
                row.search_text = label.lower()
                row.get_style_context().add_class("page-row")
                line = Gtk.Box(spacing=10)
                tile = Gtk.Box()
                tile.get_style_context().add_class("tile")
                tile.get_style_context().add_class(tile_class)
                glyph = self._icon(icon, 15)
                glyph.set_halign(Gtk.Align.CENTER)
                glyph.set_valign(Gtk.Align.CENTER)
                tile.pack_start(glyph, True, True, 0)
                line.pack_start(tile, False, False, 0)
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
        # Section headers disappear while searching, macOS Settings style.
        if getattr(row, "page_name", None) is None:
            return False
        return self._sidebar_query in getattr(row, "search_text", "")

    def _on_stack_page_changed(self, _stack, _param):
        name = self.stack.get_visible_child_name()
        if not name:
            return
        for row in self.sidebar_list.get_children():
            if getattr(row, "page_name", None) == name:
                self.sidebar_list.select_row(row)
                break

    # ------------------------------------------------------------------
    # Task runner
    # ------------------------------------------------------------------
    def submit(self, func, *args, done=None):
        """Queue a backend function for a worker thread.

        Tasks run one at a time in FIFO order instead of being rejected while
        another task is running; ``done`` always runs on the UI thread.
        """
        self._queue.append((func, args, done))
        self._pump_queue()
        return True

    def _pump_queue(self):
        with self._busy_lock:
            if self._busy or not self._queue:
                return
            func, args, done = self._queue.popleft()
            self._busy = True
        GLib.idle_add(self._set_busy_ui, True)

        def target():
            try:
                if utils.accepts_log(func):
                    result = func(*args, log=self.log_buf)
                else:
                    result = func(*args)
            except Exception as exc:  # never let a worker die silently
                self.log_buf.append("[error] {}: {}\n{}\n".format(
                    type(exc).__name__, exc, traceback.format_exc(limit=6)))
                result = utils.fail("{}: {}".format(type(exc).__name__, exc))
            GLib.idle_add(self._finish, result, done)

        threading.Thread(target=target, daemon=True).start()

    def _set_busy_ui(self, busy):
        self.spinner.start() if busy else self.spinner.stop()
        self.status_label.set_text("Working…" if busy else "Ready")
        for widget in self.action_widgets:
            widget.set_sensitive(not busy)
        return False

    def _finish(self, result, done):
        with self._busy_lock:
            self._busy = False
        self._set_busy_ui(False)
        self._pump_queue()
        if isinstance(result, utils.Outcome):
            prefix = "[ok] " if result.ok else "[failed] "
            self.log_buf.append(prefix + result.message + "\n")
            for detail in result.details:
                self.log_buf.append("    - " + detail + "\n")
            if result.ok:
                self.status_label.set_text(result.message)
            else:
                summary = result.message
                if result.details:
                    summary += ": " + result.details[0][:180]
                self._notify("Action failed: " + summary, "error")
        if done is not None:
            try:
                done(result)
            except Exception as exc:
                self.log_buf.append("[error] UI update failed: {}\n".format(exc))
        return False

    def _start_initial_tasks(self):
        # The FIFO queue runs these one at a time without dropping any.
        self.submit(apps_backend.get_status_label_map, done=self._apply_status)
        self.submit(self._scan_installed_worker, done=self._fill_manage_rows)
        self.submit(dash_backend.get_system_info, done=self._apply_stats)
        self.submit(deepclean_backend.scan_cleanable, done=self._apply_clean_scan)
        self.submit(services_backend.boot_info, done=self._apply_boot)
        self.submit(services_backend.list_services, done=self._apply_services)
        self.submit(backup_backend.list_snapshots, done=self._apply_snapshots)
        self.submit(self._read_settings, done=self._apply_settings)
        interval = self.settings.get("auto_refresh_seconds", 15)
        if interval:
            GLib.timeout_add_seconds(interval, self._periodic_refresh)

    def _periodic_refresh(self):
        with self._busy_lock:
            busy = self._busy
        if not busy:
            self.submit(dash_backend.get_system_info, done=self._apply_stats)
        return True

    # ------------------------------------------------------------------
    # Feedback (non-modal) and dialogs
    # ------------------------------------------------------------------
    def _notify(self, message, level="info"):
        """Show a dismissible banner instead of blocking the user with a modal."""
        message = str(message).strip()
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
        self.banner.show()
        self.banner.set_revealed(True)
        self.status_label.set_text(message[:100])
        self.log_buf.append("[{}] {}\n".format(level, message))

    def _dismiss_banner(self, *_args):
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

    def _confirm(self, title, message):
        if not self.settings.get("confirm_destructive", True):
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
            "dashboard", "Dashboard", "Welcome to Preen",
            "Install apps, clean up packages and tune your system, with a dry-run switch "
            "so you can see exactly what will happen first.", icon="computer-symbolic")

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hero.get_style_context().add_class("hero-card")
        self.hero_os = Gtk.Label(label="Reading system information…")
        self.hero_os.set_xalign(0)
        self.hero_os.get_style_context().add_class("hero-os")
        self.lbl_stats = Gtk.Label(label="One moment, collecting CPU, memory and disk data.")
        self.lbl_stats.set_xalign(0)
        self.lbl_stats.set_line_wrap(True)
        self.lbl_stats.get_style_context().add_class("hero-meta")
        hero.pack_start(self.hero_os, False, False, 0)
        hero.pack_start(self.lbl_stats, False, False, 0)
        page.pack_start(hero, False, False, 0)

        stat_row = Gtk.Box(spacing=12, homogeneous=True)
        self.stat_bars = {}
        for key, name, icon in (("cpu", "CPU", "speedometer-symbolic"),
                                ("mem", "Memory", "drive-multidisk-symbolic"),
                                ("disk", "Disk", "drive-harddisk-symbolic"),
                                ("swap", "Swap", "media-memory-symbolic")):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("stat-card")
            card.get_style_context().add_class("stat-{}".format(key))
            head = Gtk.Box(spacing=7)
            head.pack_start(self._icon(icon), False, False, 0)
            name_label = Gtk.Label(label=name)
            name_label.set_xalign(0)
            name_label.get_style_context().add_class("stat-name")
            head.pack_start(name_label, False, False, 0)
            value = Gtk.Label(label="…")
            value.set_xalign(0)
            value.get_style_context().add_class("stat-value")
            bar = Gtk.ProgressBar()
            bar.set_show_text(False)
            card.pack_start(head, False, False, 0)
            card.pack_start(value, False, False, 0)
            card.pack_start(bar, False, False, 0)
            stat_row.pack_start(card, True, True, 0)
            self.stat_bars[key] = (value, bar)
        page.pack_start(stat_row, False, False, 0)

        getting_started, inner = self._frame("Getting started", icon="mail-send-receive-symbolic")
        steps = [
            ("1", "Turn on Simulate", "Top-right switch. Nothing is changed; every command is written to Logs."),
            ("2", "Choose what you need", "Install Apps for software, Optimize System for cleanup and tuning."),
            ("3", "Review and apply", "Read Logs, then switch Simulate off and repeat the action for real."),
        ]
        for number, heading, detail in steps:
            line = Gtk.Box(spacing=10)
            badge = Gtk.Label(label=number)
            badge.set_valign(Gtk.Align.CENTER)
            badge.get_style_context().add_class("step-number")
            text = Gtk.Label()
            text.set_markup("<b>{}:</b> {}".format(_escape_markup(heading),
                                                    _escape_markup(detail)))
            text.set_xalign(0)
            text.set_line_wrap(True)
            line.pack_start(badge, False, False, 0)
            line.pack_start(text, True, True, 0)
            inner.pack_start(line, False, False, 0)
        page.pack_start(getting_started, False, False, 0)

        health_frame, health_inner = self._frame("Tool availability", icon="emblem-system-symbolic")
        self.health_chips = Gtk.Box(spacing=6)
        self.lbl_health = Gtk.Label(label="Checking installed tools…")
        self.lbl_health.set_xalign(0)
        self.lbl_health.set_line_wrap(True)
        self.lbl_health.get_style_context().add_class("hint-label")
        health_inner.pack_start(self.health_chips, False, False, 0)
        health_inner.pack_start(self.lbl_health, False, False, 0)
        page.pack_start(health_frame, False, False, 0)

        buttons = self._row(
            self._button("Refresh Status", self._refresh_stats,
                         "Re-read CPU, memory, disk and OS information", primary=True,
                         icon="view-refresh-symbolic"),
            self._button("Run Cleanup Now", self.on_dashboard_cleanup,
                         "APT autoremove/autoclean plus unused Flatpak runtimes",
                         icon="user-trash-symbolic"),
            self._button("Open Logs", self.on_open_logs_page,
                         "See the exact commands that were run",
                         icon="document-open-recent-symbolic"),
        )
        page.pack_start(buttons, False, False, 0)

    def _refresh_stats(self, _btn=None):
        self.submit(dash_backend.get_system_info, done=self._apply_stats)

    def _apply_stats(self, info):
        if not isinstance(info, dict):
            return
        values = {key: info.get(key, "?") for key in (
            "cpu_percent", "cpu_cores", "mem_percent", "mem_used",
            "disk_percent", "disk_used", "swap_percent", "swap_used",
            "load_average", "os", "kernel", "uptime", "power_profile")}

        def fraction(percent):
            try:
                return max(0.0, min(1.0, float(str(percent).rstrip("%")) / 100.0))
            except (TypeError, ValueError):
                return 0.0

        self.hero_os.set_text(str(values["os"]))
        meta = "Kernel {kernel}  ·  uptime {uptime}  ·  power profile: {power_profile}".format(**values)
        if values.get("load_average") and values["load_average"] != "?":
            meta += "  ·  load avg: {load_average}".format(**values)
        self.lbl_stats.set_text(meta)
        self.stat_bars["cpu"][0].set_text("{}%  ·  {} cores".format(
            values["cpu_percent"], values["cpu_cores"]))
        self.stat_bars["cpu"][1].set_fraction(fraction(values["cpu_percent"]))
        self.stat_bars["mem"][0].set_text("{}%  ·  {}".format(
            values["mem_percent"], values["mem_used"]))
        self.stat_bars["mem"][1].set_fraction(fraction(values["mem_percent"]))
        self.stat_bars["disk"][0].set_text("{}%  ·  {}".format(
            values["disk_percent"], values["disk_used"]))
        self.stat_bars["disk"][1].set_fraction(fraction(values["disk_percent"]))
        self.stat_bars["swap"][0].set_text("{}%  ·  {}".format(
            values["swap_percent"], values["swap_used"]))
        self.stat_bars["swap"][1].set_fraction(fraction(values["swap_percent"]))

    def on_open_logs_page(self, _btn=None):
        self.stack.set_visible_child_name("logs")

    def on_dashboard_cleanup(self, _btn):
        if self._confirm("Run system cleanup?",
                         "Runs apt autoremove/autoclean and removes unused Flatpak runtimes."):
            self.submit(system_backend.run_cleanup)

    # ------------------------------------------------------------------
    # Install page
    # ------------------------------------------------------------------
    def _build_install_page(self):
        page = self._page(
            "install", "Install Apps", "Install Apps",
            "Tick what you want, then press Install Selected. The preferred source is used "
            "first; if an app is not available there, the other source is used automatically.",
            icon="system-software-install-symbolic")

        toolbar = Gtk.Box(spacing=8)
        toolbar.pack_start(Gtk.Label(label="Preferred source:"), False, False, 0)
        self.install_source = self._segmented(
            ("Flatpak", "APT"),
            active_index=1 if self.settings.get("default_source") == "apt" else 0,
            tooltip="Falls back to the other source when an app is unavailable")
        for button in self._segmented_buttons(self.install_source):
            button.connect("clicked", lambda _b: self._on_source_changed())
        toolbar.pack_start(self.install_source, False, False, 0)

        self.install_search = Gtk.SearchEntry()
        self.install_search.set_placeholder_text("Search apps…")
        self.install_search.set_hexpand(True)
        self.install_search.connect("search-changed", self._on_install_search_changed)
        toolbar.pack_start(self.install_search, True, True, 0)
        toolbar.pack_start(self._header_button("Select all", self.on_select_all,
                                               "Tick every app currently visible"), False, False, 0)
        toolbar.pack_start(self._header_button("Clear", self.on_select_none,
                                               "Untick every app"), False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.install_empty = self._hint("No apps match your search. Clear the search box to see all apps.")
        self.install_empty.set_no_show_all(True)
        self.install_empty.hide()

        self.install_list = Gtk.ListBox()
        self.install_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.install_list.set_filter_func(self._install_filter, None)
        for category, items in apps_backend.load_apps().items():
            header_row = Gtk.ListBoxRow()
            header_row.set_activatable(False)
            header_row.is_header = True
            header_row.get_style_context().add_class("list-header")
            header_label = Gtk.Label()
            header_label.set_markup("<b>{}</b>".format(_escape_markup(category)))
            header_label.set_xalign(0)
            header_row.add(header_label)
            self.install_list.add(header_row)
            for item in items:
                app_id = item["id"]
                row = Gtk.ListBoxRow()
                row.is_header = False
                row.app_id = app_id
                row.get_style_context().add_class("app-row")
                row.search_text = (item["name"] + " " + category + " " + app_id).lower()
                line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                chk = Gtk.CheckButton()
                chk.connect("toggled", lambda _c: self._update_install_counter())
                name = Gtk.Label(label=item["name"])
                name.set_xalign(0)
                name.set_hexpand(True)
                name.set_tooltip_text(item.get("note", ""))
                badge = Gtk.Label(label=self._source_badge(item))
                badge.set_tooltip_text(item.get("note") or self._source_badge(item))
                badge.get_style_context().add_class("badge")
                status = Gtk.Label(label="Checking…")
                status.set_width_chars(22)
                status.set_xalign(0)
                status.get_style_context().add_class("dim-label")
                line.pack_start(chk, False, False, 0)
                line.pack_start(name, True, True, 0)
                line.pack_start(badge, False, False, 0)
                line.pack_start(status, False, False, 0)
                row.add(line)
                row.chk = chk
                row.status_label = status
                self.app_rows[app_id] = row
                self.install_list.add(row)

        scroller = Gtk.ScrolledWindow()
        scroller.add(self.install_list)
        page.pack_start(self.install_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.install_counter = self._counter("No apps selected")
        preset_row = Gtk.Box(spacing=8)
        preset_row.pack_start(Gtk.Label(label="Quick picks:"), False, False, 0)
        self.cmb_presets = Gtk.ComboBoxText()
        self.cmb_presets.append_text("Choose a preset…")
        self.presets = apps_backend.load_presets()
        for name in self.presets:
            self.cmb_presets.append_text(name)
        self.cmb_presets.set_active(0)
        preset_row.pack_start(self.cmb_presets, False, False, 0)
        preset_row.pack_start(self._button("Apply Preset", self.on_apply_preset,
                                           "Tick all apps in the chosen preset"), False, False, 0)
        preset_row.pack_end(self.install_counter, True, True, 0)
        page.pack_start(preset_row, False, False, 0)

        actions = self._row(
            self._button("Install Selected", self.on_install_selected,
                         "Install the ticked apps (honours Simulate mode)", primary=True,
                         icon="system-software-install-symbolic"),
            self._button("Update Selected", self.on_update_selected,
                         "Update only the ticked apps"),
            self._button("Update All", self.on_update_all,
                         "Update every package from the selected source"),
            self._button("Uninstall Selected", self.on_uninstall_selected,
                         "Remove the ticked apps", destructive=True),
            self._button("Refresh Status", self.on_refresh_status,
                         "Re-check which apps are installed"),
        )
        page.pack_start(actions, False, False, 0)

    @staticmethod
    def _source_badge(item):
        has_flat, has_apt = bool(item.get("flatpak")), bool(item.get("apt"))
        if has_flat and has_apt:
            return "Flatpak + APT"
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
        count = len(self._selected_apps())
        source = (self.install_source.get_active_text() or "Flatpak")
        self.install_counter.set_text(
            "{} selected · preferred source: {}".format(count, source))

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

    def on_select_all(self, _btn):
        query = self._install_query()
        for row in self.app_rows.values():
            if not query or query in row.search_text:
                row.chk.set_active(True)
        self._update_install_counter()

    def on_select_none(self, _btn):
        for row in self.app_rows.values():
            row.chk.set_active(False)
        self._update_install_counter()

    def on_refresh_status(self, _btn=None):
        apps_backend.invalidate_state()
        self.submit(apps_backend.get_status_label_map, done=self._apply_status)

    def _apply_status(self, result):
        if not isinstance(result, dict):
            return
        for app_id, row in self.app_rows.items():
            label = result.get(app_id, "Unknown")
            row.status_label.set_text(label)
            row.status_label.set_tooltip_text(label)
            context = row.status_label.get_style_context()
            for css_class in ("dim-label", "badge", "badge-ok", "badge-bad"):
                context.remove_class(css_class)
            context.add_class("badge")
            if "installed" in label.lower() and "not" not in label.lower():
                context.add_class("badge-ok")
            elif label.lower().startswith("not "):
                context.add_class("badge-bad")
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
                        done=lambda _r: self.on_refresh_status())

    def on_update_selected(self, _btn):
        app_ids = self._require_selection()
        if app_ids:
            self.submit(apps_backend.update_apps, app_ids, self._source(),
                        done=lambda _r: self.on_refresh_status())

    def on_uninstall_selected(self, _btn):
        app_ids = self._require_selection()
        if not app_ids:
            return
        if not self._confirm("Uninstall {} app(s)?".format(len(app_ids)),
                             "Removes the installed APT/Flatpak packages for the selected apps."):
            return
        self.submit(apps_backend.uninstall_apps, app_ids, self._source(),
                    done=lambda _r: self.on_refresh_status())

    def on_update_all(self, _btn):
        source = self._source()
        if not self._confirm("Update all {} packages?".format(source.upper()),
                             "Runs a full {} update and may take several minutes.".format(source)):
            return
        self.submit(apps_backend.update_all, source,
                    done=lambda _r: self.on_refresh_status())

    # ------------------------------------------------------------------
    # Manage page
    # ------------------------------------------------------------------
    def _build_manage_page(self):
        page = self._page(
            "manage", "Manage Apps", "Manage Installed Apps",
            "Shows Flatpak apps and graphical APT applications. Core system packages are "
            "locked so you cannot break your desktop by accident.",
            icon="application-x-executable-symbolic")

        toolbar = Gtk.Box(spacing=8)
        self.manage_search = Gtk.SearchEntry()
        self.manage_search.set_placeholder_text("Search installed apps…")
        self.manage_search.set_hexpand(True)
        self.manage_search.connect("search-changed", self._on_manage_search_changed)
        toolbar.pack_start(self.manage_search, True, True, 0)
        toolbar.pack_start(self._button("Scan Installed", self.on_scan_installed,
                                        "Re-scan Flatpak and APT applications", primary=True,
                                        icon="edit-find-symbolic"),
                           False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        self.manage_empty = self._hint(
            "No installed apps found. Install Flatpak, then press Scan Installed.")
        self.manage_empty.set_no_show_all(True)
        self.manage_empty.hide()

        self.manage_listbox = Gtk.ListBox()
        self.manage_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.manage_listbox.set_filter_func(self._manage_filter, None)
        scroller = Gtk.ScrolledWindow()
        scroller.add(self.manage_listbox)
        page.pack_start(self.manage_empty, False, False, 0)
        page.pack_start(scroller, True, True, 0)

        self.manage_counter = self._counter("Nothing selected")
        counter_row = Gtk.Box(spacing=8)
        counter_row.pack_end(self.manage_counter, True, True, 0)
        page.pack_start(counter_row, False, False, 0)

        actions = self._row(
            self._button("Update Selected", self.on_update_scanned,
                         "Update the ticked installed apps", primary=True),
            self._button("Uninstall Selected", self.on_uninstall_scanned,
                         "Remove the ticked installed apps", destructive=True),
        )
        page.pack_start(actions, False, False, 0)
        page.pack_start(self._hint(
            "Rows marked protected are core desktop packages. Their checkboxes are "
            "disabled so a cleanup cannot break your session."),
            False, False, 0)

    @staticmethod
    def _scan_installed_worker():
        return apps_backend.list_installed_flatpak() + apps_backend.list_installed_apt()

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
                "No installed apps found. Install Flatpak, then press Scan Installed.")
            self.manage_empty.show()
        else:
            self.manage_empty.hide()

    def on_scan_installed(self, _btn=None):
        self.submit(self._scan_installed_worker, done=self._fill_manage_rows)

    def _update_manage_counter(self):
        count = len(self._selected_manage())
        self.manage_counter.set_text("{} selected".format(count))

    def _fill_manage_rows(self, entries):
        if not isinstance(entries, list):
            return
        for row in list(self.manage_listbox.get_children()):
            self.manage_listbox.remove(row)
        for entry in sorted(entries, key=lambda e: (e["source"], e["name"].lower())):
            row = Gtk.ListBoxRow()
            row.entry = entry
            row.get_style_context().add_class("app-row")
            row.search_text = (entry["name"] + " " + entry["id"] + " " + entry["source"]).lower()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            chk = Gtk.CheckButton()
            chk.set_sensitive(not entry.get("protected"))
            chk.connect("toggled", lambda _c: self._update_manage_counter())
            label = Gtk.Label(label=entry["name"])
            label.set_xalign(0)
            label.set_hexpand(True)
            source = Gtk.Label(label=entry["source"])
            source.get_style_context().add_class("badge")
            line.pack_start(chk, False, False, 0)
            line.pack_start(label, True, True, 0)
            line.pack_start(source, False, False, 0)
            if entry.get("protected"):
                lock = Gtk.Box(spacing=5)
                lock.pack_start(self._icon("changes-prevent-symbolic", 14), False, False, 0)
                lock_label = Gtk.Label(label="protected")
                lock_label.get_style_context().add_class("hint-label")
                lock.pack_start(lock_label, False, False, 0)
                line.pack_start(lock, False, False, 0)
            row.add(line)
            row.chk = chk
            self.manage_listbox.add(row)
        self.manage_listbox.show_all()
        self._update_manage_counter()
        self._on_manage_search_changed(None)
        self._notice("Found {} installed app(s).".format(len(entries)))

    def _selected_manage(self):
        selected = []
        for row in self.manage_listbox.get_children():
            chk = getattr(row, "chk", None)
            if chk is not None and chk.get_active() and chk.get_sensitive():
                selected.append(row.entry)
        return selected

    def on_uninstall_scanned(self, _btn):
        selected = self._selected_manage()
        if not selected:
            self._notify("Tick at least one installed app first.", "warning")
            return
        if not self._confirm("Uninstall {} package(s)?".format(len(selected)),
                             "\n".join("• {} ({})".format(e["name"], e["source"]) for e in selected)):
            return
        self.submit(apps_backend.uninstall_installed, selected,
                    done=lambda _r: self.on_scan_installed())

    def on_update_scanned(self, _btn):
        selected = self._selected_manage()
        if not selected:
            self._notify("Tick at least one installed app first.", "warning")
            return
        self.submit(apps_backend.update_installed, selected)

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
            "Creates /swapfile and adds it to /etc/fstab",
            tooltip="Creates /swapfile and adds it to /etc/fstab")
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
            "Needs systemd-zram-generator")
        power.pack_start(zram_row, False, False, 0)

        self.cmb_power = Gtk.ComboBoxText()
        for profile in perf_backend.POWER_PROFILES:
            self.cmb_power.append_text(profile)
        self.cmb_power.set_active(0)
        self.cmb_power.set_tooltip_text("Requires power-profiles-daemon")
        power.pack_start(self._value_row("Power profile", self.cmb_power,
                                         "Requires power-profiles-daemon"),
                         False, False, 0)
        page.pack_start(power_frame, False, False, 0)
        self._on_swap_toggle(None)

        page.pack_start(self._row(
            self._button("Apply Changes", self.on_run_optimize,
                         "Apply only the settings you changed", primary=True,
                         icon="object-select-symbolic"),
            self._button("Reload Current Settings", self._refresh_settings,
                         "Re-read the current state of your system"),
        ), False, False, 0)
        page.pack_start(self._hint(
            "Current settings are detected automatically. If nothing changed, nothing runs."),
            False, False, 0)

    def _on_swap_toggle(self, _switch, _param=None):
        # The size combo only matters while a swapfile is being enabled.
        self.cmb_swap_size.set_sensitive(self.chk_swap.get_active())

    def _read_settings(self):
        return {
            "animations_off": not system_backend.are_animations_enabled(),
            "swap": perf_backend.is_swapfile_active(),
            "zram": perf_backend.is_zram_active() or perf_backend.is_zram_configured(),
            "power": perf_backend.get_power_profile() or "balanced",
            "theme": ui_backend.get_theme_mode(),
            "round": ui_backend.are_rounded_corners_enabled(),
            "scaling": ui_backend.get_text_scaling(),
            "warnings": dash_backend.feature_warnings(),
        }

    def _apply_settings(self, info):
        if not isinstance(info, dict):
            return
        self.baseline = info
        self.chk_animations.set_active(bool(info.get("animations_off")))
        self.chk_swap.set_active(bool(info.get("swap")))
        self.chk_zram.set_active(bool(info.get("zram")))
        profile = info.get("power", "balanced")
        if profile in perf_backend.POWER_PROFILES:
            self.cmb_power.set_active(perf_backend.POWER_PROFILES.index(profile))
        self.cmb_theme.set_active(1 if info.get("theme") == "dark" else 0)
        self.chk_round.set_active(bool(info.get("round")))
        current_scaling = float(info.get("scaling", 1.0) or 1.0)
        scaling_index = 0
        for index, (_label, factor) in enumerate(self.SCALING_OPTIONS):
            if abs(factor - current_scaling) < 0.011:
                scaling_index = index
                break
        self.cmb_scaling.set_active(scaling_index)
        self._on_swap_toggle(None)

        warnings = info.get("warnings") or []
        for child in list(self.health_chips.get_children()):
            self.health_chips.remove(child)
        if warnings:
            self.health_chips.pack_start(
                self._chip("{} tool(s) missing".format(len(warnings)), "chip-bad"),
                False, False, 0)
            self.lbl_health.set_text("\n".join("• " + w for w in warnings))
            if self.settings.get("show_dependency_warnings", True):
                self._notify(
                    "{} optional tool(s) missing, so some features are unavailable. "
                    "See Dashboard → Tool availability.".format(len(warnings)), "warning")
        else:
            self.health_chips.pack_start(
                self._chip("All tools available", "chip-ok"), False, False, 0)
            self.lbl_health.set_text("Everything is ready. Every optional tool is installed.")

    def _refresh_settings(self, *_args):
        self.submit(self._read_settings, done=self._apply_settings)

    def on_run_optimize(self, _btn):
        opts = {
            "cleanup": self.chk_cleanup.get_active(),
            "animations_off": self.chk_animations.get_active(),
            "swap": self.chk_swap.get_active(),
            "swap_size": self._swap_size(),
            "zram": self.chk_zram.get_active(),
            "power": self.cmb_power.get_active_text() or "balanced",
        }
        actions = []
        if opts["cleanup"]:
            actions.append(("System cleanup", system_backend.run_cleanup, ()))
        if opts["animations_off"] != self.baseline.get("animations_off"):
            actions.append(("GNOME animations", system_backend.set_animations,
                            (not opts["animations_off"],)))
        if opts["power"] != self.baseline.get("power"):
            actions.append(("Power profile", perf_backend.set_power_profile, (opts["power"],)))
        if opts["swap"] != self.baseline.get("swap"):
            actions.append(("Swapfile", perf_backend.enable_swapfile if opts["swap"] else perf_backend.disable_swapfile,
                            (opts["swap_size"],) if opts["swap"] else ()))
        if opts["zram"] != self.baseline.get("zram"):
            actions.append(("ZRAM", perf_backend.enable_zram if opts["zram"] else perf_backend.disable_zram, ()))
        if not actions:
            self._notify("Nothing to apply. Your settings already match.", "info")
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_settings())

    def on_manage_startup(self, _btn):
        items = system_backend.list_startup_apps()
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
        self.submit(utils.run_actions, actions)

    # ------------------------------------------------------------------
    # Customize page
    # ------------------------------------------------------------------
    def _build_customize_page(self):
        page = self._page(
            "customize", "Customize Look", "Customize Look",
            "Change the light/dark theme, install an icon pack and add rounded corners. "
            "Only GTK themes already installed on your system are applied.",
            icon="preferences-desktop-appearance")

        theme_frame, theme = self._frame("Theme", tight=True)
        self.cmb_theme = Gtk.ComboBoxText()
        self.cmb_theme.append_text("Light")
        self.cmb_theme.append_text("Dark")
        self.cmb_theme.set_active(0)
        theme.pack_start(self._value_row("Appearance", self.cmb_theme,
                                         "Switch the GNOME colour scheme"),
                         False, False, 0)

        self.SCALING_OPTIONS = (
            ("Default (100%)", 1.0),
            ("Large (115%)", 1.15),
            ("Larger (125%)", 1.25),
            ("Small (85%)", 0.85),
        )
        self.cmb_scaling = Gtk.ComboBoxText()
        for label, _factor in self.SCALING_OPTIONS:
            self.cmb_scaling.append_text(label)
        self.cmb_scaling.set_active(0)
        self.cmb_scaling.set_tooltip_text("GNOME text scaling factor, applied desktop-wide")
        theme.pack_start(self._value_row("Text size", self.cmb_scaling,
                                         "GNOME scaling factor, applied desktop-wide"),
                         False, False, 0)
        apply_theme_row = Gtk.Box()
        apply_theme_row.get_style_context().add_class("settings-row")
        apply_theme_row.pack_start(
            self._button("Apply Theme Now", self.on_apply_theme,
                         "Switch the GNOME colour scheme immediately", icon="object-select-symbolic",
                         flat=True),
            False, False, 0)
        theme.pack_start(apply_theme_row, False, False, 0)
        page.pack_start(theme_frame, False, False, 0)

        extras_frame, extras = self._frame("Extras", tight=True)
        round_row, self.chk_round = self._toggle_row(
            "Rounded corners",
            "Adds a reversible rule to ~/.config/gtk-3.0/gtk.css")
        extras.pack_start(round_row, False, False, 0)
        icon_row = Gtk.Box()
        icon_row.get_style_context().add_class("settings-row")
        icon_row.pack_start(self._button("Install Icon Pack…", self.on_install_icon,
                                         "Choose a .tar.xz or .tar.gz icon theme",
                                         icon="folder-download-symbolic", flat=True),
                            False, False, 0)
        extras.pack_start(icon_row, False, False, 0)
        extras.pack_start(self._hint("Rounded-corner CSS is reversible and may need an app restart to show."),
                          False, False, 0)
        page.pack_start(extras_frame, False, False, 0)

        page.pack_start(self._row(
            self._button("Apply Look Changes", self.on_apply_look,
                         "Apply the theme and corner changes you made", primary=True,
                         icon="object-select-symbolic"),
            self._button("Reload Current Look", self._refresh_settings,
                         "Re-read the current theme and CSS state"),
        ), False, False, 0)

    def _theme_mode(self):
        return "dark" if (self.cmb_theme.get_active_text() or "Light").lower() == "dark" else "light"

    def on_apply_theme(self, _btn):
        self.submit(ui_backend.apply_theme_mode, self._theme_mode(),
                    done=lambda _r: self._refresh_settings())

    def on_apply_look(self, _btn):
        mode = self._theme_mode()
        actions = []
        if mode != self.baseline.get("theme"):
            actions.append(("Theme", ui_backend.apply_theme_mode, (mode,)))
        if self.chk_round.get_active() != self.baseline.get("round"):
            actions.append(("Rounded corners", ui_backend.set_rounded_corners,
                            (self.chk_round.get_active(),)))
        scaling = self.SCALING_OPTIONS[self.cmb_scaling.get_active()][1]
        if abs(float(scaling) - float(self.baseline.get("scaling", 1.0))) > 0.011:
            actions.append(("Text size", ui_backend.set_text_scaling, (scaling,)))
        if not actions:
            self._notify("Nothing to apply. Your look already matches.", "info")
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_settings())

    def on_install_icon(self, _btn):
        dialog = Gtk.FileChooserDialog(title="Select icon pack", parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and path:
            self.submit(ui_backend.install_icon_pack, path)

    # ------------------------------------------------------------------
    # Deep Clean page
    # ------------------------------------------------------------------
    def _build_deepclean_page(self):
        page = self._page(
            "deepclean", "Deep Clean", "Deep Clean",
            "See exactly how much space each item reclaims before anything is deleted. "
            "Root items need your password via polkit; Simulate mode previews every step.",
            icon="user-trash-symbolic")

        scan_card, scan_inner = self._frame(
            "Reclaimable space", icon="drive-harddisk-symbolic")
        scan_toolbar = Gtk.Box(spacing=8)
        scan_toolbar.pack_start(self._header_button(
            "Select all", self.on_clean_select_all, "Tick every cleanable item"), False, False, 0)
        scan_toolbar.pack_start(self._header_button(
            "Clear", self.on_clean_select_none, "Untick every item"), False, False, 0)
        self.clean_counter = self._counter("No items selected")
        scan_toolbar.pack_end(self.clean_counter, True, True, 0)
        scan_inner.pack_start(scan_toolbar, False, False, 0)
        self.clean_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.clean_total = self._hint("Press Scan Now to measure what can be reclaimed.")
        scan_inner.pack_start(self.clean_rows, False, False, 0)
        scan_inner.pack_start(self.clean_total, False, False, 0)
        page.pack_start(scan_card, False, False, 0)

        page.pack_start(self._row(
            self._button("Scan Now", self.on_scan_cleanable,
                         "Measure reclaimable space", primary=True,
                         icon="edit-find-symbolic"),
            self._button("Clean Selected", self.on_clean_selected,
                         "Delete the ticked items (honours Simulate mode)",
                         icon="user-trash-symbolic"),
        ), False, False, 0)
        page.pack_start(self._hint(
            "Thumbnails are regenerated automatically; trash cleaning empties "
            "the wastebasket. The journal keeps its most recent 100 MB."),
            False, False, 0)

    def on_clean_select_all(self, _btn=None):
        for chk, _item in self.clean_checkbuttons.values():
            chk.set_active(True)
        self._update_clean_counter()

    def on_clean_select_none(self, _btn=None):
        for chk, _item in self.clean_checkbuttons.values():
            chk.set_active(False)
        self._update_clean_counter()

    def _update_clean_counter(self, *_args):
        selected = [item for chk, item in self.clean_checkbuttons.values()
                    if chk.get_active()]
        if not selected:
            self.clean_counter.set_text("No items selected")
            return
        total = deepclean_backend.total_size(selected)
        self.clean_counter.set_text("{} selected · reclaim {}".format(
            len(selected), deepclean_backend.format_size(total)))

    def _apply_clean_scan(self, items):
        if not isinstance(items, list):
            return
        for child in list(self.clean_rows.get_children()):
            self.clean_rows.remove(child)
        self.clean_checkbuttons = {}
        for item in items:
            line = Gtk.Box(spacing=10)
            chk = Gtk.CheckButton()
            chk.set_valign(Gtk.Align.CENTER)
            chk.connect("toggled", self._update_clean_counter)
            line.pack_start(chk, False, False, 0)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            name = Gtk.Label(label=item["label"])
            name.set_xalign(0)
            text_box.pack_start(name, False, False, 0)
            detail = Gtk.Label(label=item["detail"])
            detail.set_xalign(0)
            detail.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            detail.get_style_context().add_class("hint-label")
            text_box.pack_start(detail, False, False, 0)
            size = Gtk.Label(label=deepclean_backend.format_size(item["size"]))
            size.get_style_context().add_class("chip")
            if item["size"] > 0:
                size.get_style_context().add_class("chip-ok")
            line.pack_start(text_box, True, True, 0)
            line.pack_start(size, False, False, 0)
            self.clean_rows.pack_start(line, False, False, 0)
            self.clean_checkbuttons[item["key"]] = (chk, item)
        self.clean_rows.show_all()
        self.clean_total.set_text("Total reclaimable: {}".format(
            deepclean_backend.format_size(deepclean_backend.total_size(items))))
        self._update_clean_counter()

    def on_scan_cleanable(self, _btn=None):
        self.submit(deepclean_backend.scan_cleanable, done=self._apply_clean_scan)

    def on_clean_selected(self, _btn):
        selected = [item for chk, item in self.clean_checkbuttons.values()
                    if chk.get_active()]
        if not selected:
            self._notify("Tick at least one item to clean.", "warning")
            return
        actions = deepclean_backend.build_clean_actions(selected)
        if not actions:
            self._notify("Nothing selected can be cleaned.", "warning")
            return
        if not self._confirm(
                "Clean {} item(s)?".format(len(selected)),
                "Deletes the selected caches and trash contents. This cannot be undone."):
            return
        self.submit(utils.run_actions, actions,
                    done=lambda _r: self.on_scan_cleanable())

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

        page.pack_start(self._row(
            self._button("Start", lambda b: self.on_service_action("start"),
                         "Start the selected service now"),
            self._button("Stop", lambda b: self.on_service_action("stop"),
                         "Stop the selected service"),
            self._button("Restart", lambda b: self.on_service_action("restart"),
                         "Restart the selected service"),
            self._button("Enable", lambda b: self.on_service_action("enable"),
                         "Enable at boot"),
            self._button("Disable", lambda b: self.on_service_action("disable"),
                         "Do not start at boot"),
        ), False, False, 0)
        page.pack_start(self._hint(
            "Green means running, red means failed, grey means stopped. Only change "
            "services you understand, since some are needed for sound, networking or the desktop."),
            False, False, 0)

    def _on_services_filter_changed(self, _widget=None):
        self.services_listbox.invalidate_filter()
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

    def _apply_services(self, entries):
        if not isinstance(entries, list):
            return
        for child in list(self.services_listbox.get_children()):
            self.services_listbox.remove(child)
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
        if not isinstance(info, dict) or not info.get("total"):
            self.lbl_boot.set_text(
                "Boot-time data is not available on this system (systemd-analyze missing).")
            return
        phases = "  ·  ".join(
            "{} {}".format(info[key], key) for key in
            ("firmware", "loader", "kernel", "userspace") if info.get(key))
        self.lbl_boot.set_text(
            "Total boot: {}  ·  {}".format(info["total"], phases or "phase breakdown unavailable"))
        for child in list(self.boot_blame.get_children()):
            self.boot_blame.remove(child)
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
        self.submit(services_backend.list_services, done=self._apply_services)
        self.submit(services_backend.boot_info, done=self._apply_boot)
        self.submit(backup_backend.list_snapshots, done=self._apply_snapshots)

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
                    done=lambda _r: self.on_refresh_services())

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
        snap.pack_start(self._row(
            self._button("Create Snapshot", self.on_snapshot,
                         "Create a Timeshift snapshot (needs Timeshift installed)"),
            self._button("Open Timeshift", self.on_open_timeshift,
                         "Launch the Timeshift graphical interface"),
            self._button("Refresh List", self.on_refresh_snapshots,
                         "Re-read saved Timeshift snapshots",
                         icon="view-refresh-symbolic"),
        ), False, False, 0)
        self.snapshot_listbox = Gtk.ListBox()
        self.snapshot_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.snapshot_empty = self._hint("No snapshots found, or Timeshift is not installed.")
        snap.pack_start(self.snapshot_empty, False, False, 0)
        snapshot_scroller = Gtk.ScrolledWindow()
        snapshot_scroller.set_min_content_height(130)
        snapshot_scroller.add(self.snapshot_listbox)
        snap.pack_start(snapshot_scroller, True, True, 0)
        snap.pack_start(self._hint("Timeshift is a separate package. If it is missing, "
                                   "install it first: sudo apt install timeshift"), False, False, 0)
        page.pack_start(snap_frame, True, True, 0)

    def on_refresh_snapshots(self, _btn=None):
        self.submit(backup_backend.list_snapshots, done=self._apply_snapshots)

    def _apply_snapshots(self, snapshots):
        if not isinstance(snapshots, list):
            return
        for row in list(self.snapshot_listbox.get_children()):
            self.snapshot_listbox.remove(row)
        self.snapshot_empty.set_visible(not snapshots)
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

        config_frame, config = self._frame("Personal settings (~/.config)")
        config.pack_start(self._row(
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

    def on_snapshot(self, _btn):
        self.submit(backup_backend.timeshift_snapshot,
                    done=lambda _r: self.on_refresh_snapshots())

    def on_open_timeshift(self, _btn):
        self.submit(backup_backend.open_timeshift_gui)

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
            self.submit(backup_backend.export_configs, path)

    def on_import_config(self, _btn):
        path = self._open_dialog("Open settings archive")
        if not path:
            return
        safe_count, unsafe = backup_backend.inspect_archive(path)
        if safe_count == 0:
            self._notify("Cannot import: archive is empty, unreadable, or has only unsafe entries.",
                         "error")
            return
        message = "This overwrites files in ~/.config with {} item(s) from the archive.".format(safe_count)
        if unsafe:
            message += "\n\n{} unsafe entr(ies) will be refused: {}".format(
                len(unsafe), ", ".join(unsafe[:5]))
        if not self._confirm("Restore settings?", message):
            return
        self.submit(backup_backend.import_configs, path)

    # ------------------------------------------------------------------
    # Logs page
    # ------------------------------------------------------------------
    def _build_logs_page(self):
        page = self._page(
            "logs", "Logs", "Activity Log",
            "Every command the app runs (or would run in Simulate mode) is written here "
            "with its exit code. Save a copy before asking for help.",
            icon="document-open-recent-symbolic")

        tools = Gtk.Box(spacing=8)
        save = self._button("Save Log…", self.on_save_log,
                            "Write the whole log to a text file", primary=True)
        clear = self._button("Clear", self.on_clear_log,
                             "Empty the log view")
        tools.pack_start(save, False, False, 0)
        tools.pack_start(clear, False, False, 0)
        scroll_switch = Gtk.Switch()
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
        scroller.add(self.log_view)
        log_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        log_card.get_style_context().add_class("card")
        log_card.pack_start(scroller, True, True, 0)
        page.pack_start(log_card, True, True, 0)

    def on_log_filter_changed(self, entry):
        self.log_buf.set_filter(entry.get_text())

    def on_toggle_auto_scroll(self, switch, _param):
        self.log_buf.auto_scroll = switch.get_active()

    def on_clear_log(self, _btn):
        self.log_buf.clear()
        self._notice("Log cleared.")

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
        confirm_switch = add_switch("Confirm destructive actions",
                                    "Ask before uninstalling or restoring settings",
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
            if settings_backend.save(values):
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
            "3. Install Apps: search, tick, then Install Selected. APT and Flatpak both work.\n"
            "4. Deep Clean: scan first, review the sizes, then clean only what you ticked.\n"
            "5. Optimize System: only the settings you changed are applied.\n"
            "6. Services: inspect boot time and start, stop or restart systemd units.\n"
            "7. Logs shows every command and its result, with a filter and Save Log for support.\n\n"
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
