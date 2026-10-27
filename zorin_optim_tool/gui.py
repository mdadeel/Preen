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

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .backend import (  # noqa: E402
    apps as apps_backend,
    backup as backup_backend,
    dashboard as dash_backend,
    performance as perf_backend,
    settings as settings_backend,
    system as system_backend,
    ui_customization as ui_backend,
    utils,
)

APP_NAME = "Zorin Optimizer"
APP_ID = "io.github.mdadeel.ZorinOptimizer"
MAX_LOG_LINES = 4000

# Small, purely cosmetic stylesheet. Wrapped in try/except at load time:
# a missing theme feature must never prevent the app from starting.
_CSS = b"""
.simulate-banner {
    background-color: #e5a50a;
    color: #1c1c1c;
    padding: 6px 12px;
    font-weight: bold;
}
.page-title { font-size: 1.35em; font-weight: bold; }
.page-subtitle { color: #888a85; }
.stat-block { font-family: monospace; padding: 8px; }
.step-number { font-weight: bold; color: #3584e4; }
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
        self._lock = threading.Lock()

    def append(self, text: str):
        text = str(text)
        with self._lock:
            self.lines.append(text)
            if len(self.lines) > MAX_LOG_LINES:
                self.lines = self.lines[-MAX_LOG_LINES:]
        GLib.idle_add(self._append, text)

    def _append(self, text: str):
        end = self.buf.get_end_iter()
        self.buf.insert(end, text)
        if self.buf.get_line_count() > MAX_LOG_LINES:
            start = self.buf.get_start_iter()
            cutoff = self.buf.get_iter_at_line(self.buf.get_line_count() - MAX_LOG_LINES)
            self.buf.delete(start, cutoff)
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
        self.set_default_size(1100, 740)
        self._busy = False
        self._busy_lock = threading.Lock()
        self.action_widgets = []
        self.app_rows = {}
        self.baseline = {
            "animations_off": False, "swap": False, "zram": False,
            "power": "balanced", "theme": "light", "round": False,
        }
        self.settings = settings_backend.load()
        if self.settings.get("simulate_on_startup"):
            utils.set_simulate(True)

        self._install_css()

        # ----- Header bar -----
        header = Gtk.HeaderBar(title=APP_NAME, subtitle="Safe system setup for Zorin OS")
        header.set_show_close_button(True)

        status_box = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.set_xalign(0)
        status_box.pack_start(self.spinner, False, False, 0)
        status_box.pack_start(self.status_label, False, False, 0)
        header.pack_start(status_box)

        header.pack_end(self._header_button("About", self.on_about,
                                           "Version, licence and links"))
        header.pack_end(self._header_button("Help", self.on_help,
                                           "Quick start guide and common questions"))
        header.pack_end(self._header_button("Preferences", self.on_preferences,
                                           "Change default source, confirmations and refresh"))

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
            label="SIMULATE MODE — commands are previewed in Logs; nothing will be changed.")
        self.sim_banner.set_name("simulate-banner")
        self.sim_banner.get_style_context().add_class("simulate-banner")
        self.sim_banner.set_no_show_all(True)

        # ----- Main layout -----
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=180)
        self.stack.set_transition_duration(180)
        sidebar = Gtk.StackSidebar(stack=self.stack)
        sidebar.set_name("main-sidebar")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.pack_start(self.banner, False, False, 0)
        body.pack_start(self.sim_banner, False, False, 0)
        panes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        panes.pack_start(sidebar, False, False, 0)
        panes.pack_start(self.stack, True, True, 0)
        body.pack_start(panes, True, True, 0)
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
        self._build_backup_page()
        self._build_logs_page()

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

    def _button(self, label, callback, tooltip=None, primary=False, destructive=False):
        button = Gtk.Button(label=label)
        button.connect("clicked", callback)
        if tooltip:
            button.set_tooltip_text(tooltip)
        context = button.get_style_context()
        if primary:
            context.add_class("suggested-action")
        if destructive:
            context.add_class("destructive-action")
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
            sub.get_style_context().add_class("dim-label")
            box.pack_start(sub, False, False, 0)
        return box

    def _page(self, name, sidebar_title, title, subtitle):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_border_width(18)
        box.pack_start(self._section(title, subtitle), False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 0)
        self.stack.add_titled(box, name, sidebar_title)
        return box

    def _frame(self, label):
        frame = Gtk.Frame(label=label)
        frame.set_border_width(2)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_border_width(12)
        frame.add(inner)
        return frame, inner

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
    # Task runner
    # ------------------------------------------------------------------
    def submit(self, func, *args, done=None):
        """Run a backend function in a worker thread; ``done`` runs on the UI thread."""
        with self._busy_lock:
            if self._busy:
                self.log_buf.append("[busy] another operation is running; please wait\n")
                return False
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
        return True

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
                    summary += " — " + result.details[0][:180]
                self._notify("Action failed: " + summary, "error")
        if done is not None:
            try:
                done(result)
            except Exception as exc:
                self.log_buf.append("[error] UI update failed: {}\n".format(exc))
        return False

    def _start_initial_tasks(self):
        # Tasks are serialised, so chain the startup reads instead of firing
        # four submits (three of which would be rejected as "busy").
        def after_scan(entries):
            self._fill_manage_rows(entries)
            self.submit(dash_backend.get_system_info, done=after_stats)

        def after_stats(info):
            self._apply_stats(info)
            self.submit(self._read_settings, done=self._apply_settings)

        def after_status(result):
            self._apply_status(result)
            self.submit(self._scan_installed_worker, done=after_scan)

        self.submit(apps_backend.get_status_label_map, done=after_status)
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
            "dashboard", "Dashboard", "Welcome to Zorin Optimizer",
            "Install apps, clean up packages and tune your system — with a dry-run switch "
            "so you can see exactly what will happen first.")

        getting_started, inner = self._frame("Getting started")
        steps = [
            ("1", "Turn on Simulate", "Top-right switch. Nothing is changed; every command is written to Logs."),
            ("2", "Choose what you need", "Install Apps for software, Optimize System for cleanup and tuning."),
            ("3", "Review and apply", "Read Logs, then switch Simulate off and repeat the action for real."),
        ]
        for number, heading, detail in steps:
            line = Gtk.Box(spacing=10)
            badge = Gtk.Label(label=number)
            badge.get_style_context().add_class("step-number")
            text = Gtk.Label()
            text.set_markup("<b>{}</b> — {}".format(_escape_markup(heading),
                                                    _escape_markup(detail)))
            text.set_xalign(0)
            text.set_line_wrap(True)
            line.pack_start(badge, False, False, 0)
            line.pack_start(text, True, True, 0)
            inner.pack_start(line, False, False, 0)
        page.pack_start(getting_started, False, False, 0)

        stats_frame, stats_inner = self._frame("System at a glance")
        self.lbl_stats = Gtk.Label(label="Reading system information…")
        self.lbl_stats.set_xalign(0)
        self.lbl_stats.set_justify(Gtk.Justification.LEFT)
        self.lbl_stats.get_style_context().add_class("stat-block")
        stats_inner.pack_start(self.lbl_stats, False, False, 0)
        page.pack_start(stats_frame, False, False, 0)

        health_frame, health_inner = self._frame("Tool availability")
        self.lbl_health = Gtk.Label(label="Checking installed tools…")
        self.lbl_health.set_xalign(0)
        self.lbl_health.set_line_wrap(True)
        health_inner.pack_start(self.lbl_health, False, False, 0)
        page.pack_start(health_frame, False, False, 0)

        buttons = self._row(
            self._button("Refresh Status", self._refresh_stats,
                         "Re-read CPU, memory, disk and OS information", primary=True),
            self._button("Run Cleanup Now", self.on_dashboard_cleanup,
                         "APT autoremove/autoclean plus unused Flatpak runtimes"),
            self._button("Open Logs", self.on_open_logs_page,
                         "See the exact commands that were run"),
        )
        page.pack_start(buttons, False, False, 0)

    def _refresh_stats(self, _btn=None):
        self.submit(dash_backend.get_system_info, done=self._apply_stats)

    def _apply_stats(self, info):
        if not isinstance(info, dict):
            return
        values = {key: info.get(key, "?") for key in (
            "cpu_percent", "cpu_cores", "mem_percent", "mem_used",
            "disk_percent", "disk_used", "os", "kernel", "uptime", "power_profile")}
        self.lbl_stats.set_text(
            "CPU {cpu_percent}%  ·  {cpu_cores} cores\n"
            "RAM {mem_percent}%  ·  {mem_used}\n"
            "Disk {disk_percent}%  ·  {disk_used}\n"
            "OS: {os}\nKernel: {kernel}  ·  Uptime: {uptime}\n"
            "Power profile: {power_profile}".format(**values))

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
            "first; if an app is not available there, the other source is used automatically.")

        toolbar = Gtk.Box(spacing=8)
        toolbar.pack_start(Gtk.Label(label="Preferred source:"), False, False, 0)
        self.install_source = Gtk.ComboBoxText()
        for text in ("Flatpak", "APT"):
            self.install_source.append_text(text)
        self.install_source.set_active(1 if self.settings.get("default_source") == "apt" else 0)
        self.install_source.set_tooltip_text("Falls back to the other source when an app is unavailable")
        self.install_source.connect("changed", lambda _c: self._on_source_changed())
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
                         "Install the ticked apps (honours Simulate mode)", primary=True),
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
            "locked so you cannot break your desktop by accident.")

        toolbar = Gtk.Box(spacing=8)
        self.manage_search = Gtk.SearchEntry()
        self.manage_search.set_placeholder_text("Search installed apps…")
        self.manage_search.set_hexpand(True)
        self.manage_search.connect("search-changed", self._on_manage_search_changed)
        toolbar.pack_start(self.manage_search, True, True, 0)
        toolbar.pack_start(self._button("Scan Installed", self.on_scan_installed,
                                        "Re-scan Flatpak and APT applications", primary=True),
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
        page.pack_start(self._hint("🔒 = protected core package. Uninstall is disabled for these."),
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
        visible = any(self._manage_filter(row, None)
                      for row in self.manage_listbox.get_children())
        self.manage_empty.set_visible(not visible and not self.manage_search.get_text())
        if not visible and not self.manage_search.get_text():
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
            row.search_text = (entry["name"] + " " + entry["id"] + " " + entry["source"]).lower()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            chk = Gtk.CheckButton()
            chk.set_sensitive(not entry.get("protected"))
            chk.connect("toggled", lambda _c: self._update_manage_counter())
            label = Gtk.Label(label="{}  ·  {}".format(entry["name"], entry["source"]))
            label.set_xalign(0)
            label.set_hexpand(True)
            line.pack_start(chk, False, False, 0)
            line.pack_start(label, True, True, 0)
            if entry.get("protected"):
                lock = Gtk.Label(label="🔒 protected")
                lock.get_style_context().add_class("dim-label")
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
            "needs your password via polkit.")

        cleanup_frame, cleanup = self._frame("Cleanup & desktop behaviour")
        self.chk_cleanup = Gtk.CheckButton.new_with_label(
            "Remove unused packages (APT autoremove/autoclean + Flatpak unused)")
        self.chk_animations = Gtk.CheckButton.new_with_label("Disable GNOME animations")
        cleanup.pack_start(self.chk_cleanup, False, False, 0)
        cleanup.pack_start(self.chk_animations, False, False, 0)
        cleanup.pack_start(self._row(self._button("Manage Startup Apps…", self.on_manage_startup,
                                                  "Enable or disable apps that launch at login")),
                           False, False, 0)
        page.pack_start(cleanup_frame, False, False, 0)

        power_frame, power = self._frame("Memory & power")
        self.chk_swap = Gtk.CheckButton.new_with_label("Use a 2 GB swapfile")
        self.chk_zram = Gtk.CheckButton.new_with_label("Enable ZRAM (needs systemd-zram-generator)")
        power_row = Gtk.Box(spacing=8)
        power_row.pack_start(Gtk.Label(label="Power profile:"), False, False, 0)
        self.cmb_power = Gtk.ComboBoxText()
        for profile in perf_backend.POWER_PROFILES:
            self.cmb_power.append_text(profile)
        self.cmb_power.set_active(0)
        self.cmb_power.set_tooltip_text("Requires power-profiles-daemon")
        power_row.pack_start(self.cmb_power, False, False, 0)
        power.pack_start(self.chk_swap, False, False, 0)
        power.pack_start(self.chk_zram, False, False, 0)
        power.pack_start(power_row, False, False, 0)
        page.pack_start(power_frame, False, False, 0)

        page.pack_start(self._row(
            self._button("Apply Changes", self.on_run_optimize,
                         "Apply only the settings you changed", primary=True),
            self._button("Reload Current Settings", self._refresh_settings,
                         "Re-read the current state of your system"),
        ), False, False, 0)
        page.pack_start(self._hint(
            "Current settings are detected automatically. If nothing changed, nothing runs."),
            False, False, 0)

    def _read_settings(self):
        return {
            "animations_off": not system_backend.are_animations_enabled(),
            "swap": perf_backend.is_swapfile_active(),
            "zram": perf_backend.is_zram_active() or perf_backend.is_zram_configured(),
            "power": perf_backend.get_power_profile() or "balanced",
            "theme": ui_backend.get_theme_mode(),
            "round": ui_backend.are_rounded_corners_enabled(),
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

        warnings = info.get("warnings") or []
        if warnings:
            self.lbl_health.set_text("\n".join("• " + w for w in warnings))
            if self.settings.get("show_dependency_warnings", True):
                self._notify(
                    "{} optional tool(s) missing — some features are unavailable. "
                    "See Dashboard → Tool availability.".format(len(warnings)), "warning")
        else:
            self.lbl_health.set_text("All optional tools are available. Everything is ready.")

    def _refresh_settings(self, *_args):
        self.submit(self._read_settings, done=self._apply_settings)

    def on_run_optimize(self, _btn):
        opts = {
            "cleanup": self.chk_cleanup.get_active(),
            "animations_off": self.chk_animations.get_active(),
            "swap": self.chk_swap.get_active(),
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
                            (2,) if opts["swap"] else ()))
        if opts["zram"] != self.baseline.get("zram"):
            actions.append(("ZRAM", perf_backend.enable_zram if opts["zram"] else perf_backend.disable_zram, ()))
        if not actions:
            self._notify("Nothing to apply — your settings already match.", "info")
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_settings())

    def on_manage_startup(self, _btn):
        items = system_backend.list_startup_apps()
        if not items:
            self._notify("No autostart entries were found on this system.", "info")
            return
        dialog = Gtk.Dialog(title="Startup Applications", parent=self, flags=0)
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
            "Only GTK themes already installed on your system are applied.")

        theme_frame, theme = self._frame("Theme")
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Appearance:"), False, False, 0)
        self.cmb_theme = Gtk.ComboBoxText()
        self.cmb_theme.append_text("Light")
        self.cmb_theme.append_text("Dark")
        self.cmb_theme.set_active(0)
        row.pack_start(self.cmb_theme, False, False, 0)
        row.pack_start(self._button("Apply Theme Now", self.on_apply_theme,
                                    "Switch the GNOME colour scheme immediately"), False, False, 0)
        theme.pack_start(row, False, False, 0)
        page.pack_start(theme_frame, False, False, 0)

        extras_frame, extras = self._frame("Extras")
        self.chk_round = Gtk.CheckButton.new_with_label("Rounded corners (adds a rule to ~/.config/gtk-3.0/gtk.css)")
        extras.pack_start(self.chk_round, False, False, 0)
        extras.pack_start(self._button("Install Icon Pack…", self.on_install_icon,
                                       "Choose a .tar.xz or .tar.gz icon theme"), False, False, 0)
        extras.pack_start(self._hint("Rounded-corner CSS is reversible and may need an app restart to show."),
                          False, False, 0)
        page.pack_start(extras_frame, False, False, 0)

        page.pack_start(self._row(
            self._button("Apply Look Changes", self.on_apply_look,
                         "Apply the theme and corner changes you made", primary=True),
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
        if not actions:
            self._notify("Nothing to apply — your look already matches.", "info")
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
    # Backup page
    # ------------------------------------------------------------------
    def _build_backup_page(self):
        page = self._page(
            "backup", "Backup & Restore", "Backup & Restore",
            "Create a Timeshift snapshot or save your personal settings. Config archives are "
            "checked before extraction so a bad archive cannot write outside ~/.config.")

        snap_frame, snap = self._frame("System snapshots (Timeshift)")
        snap.pack_start(self._row(
            self._button("Create Snapshot", self.on_snapshot,
                         "Create a Timeshift snapshot (needs Timeshift installed)"),
            self._button("Open Timeshift", self.on_open_timeshift,
                         "Launch the Timeshift graphical interface"),
        ), False, False, 0)
        snap.pack_start(self._hint("Timeshift is a separate package. If it is missing, "
                                   "install it first: sudo apt install timeshift"), False, False, 0)
        page.pack_start(snap_frame, False, False, 0)

        config_frame, config = self._frame("Personal settings (~/.config)")
        config.pack_start(self._row(
            self._button("Export Settings…", self.on_export_config,
                         "Save ~/.config to a .tar.xz archive", primary=True),
            self._button("Import Settings…", self.on_import_config,
                         "Restore ~/.config from an archive"),
        ), False, False, 0)
        config.pack_start(self._hint(
            "Import overwrites matching files in ~/.config. Export first if you are unsure."),
            False, False, 0)
        page.pack_start(config_frame, False, False, 0)

    def on_snapshot(self, _btn):
        self.submit(backup_backend.timeshift_snapshot)

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
        path = self._save_dialog("Save settings archive", "zorin-config-backup.tar.xz")
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
            "with its exit code. Save a copy before asking for help.")

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
        page.pack_start(tools, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.add(self.log_view)
        page.pack_start(scroller, True, True, 0)

    def on_toggle_auto_scroll(self, switch, _param):
        self.log_buf.auto_scroll = switch.get_active()

    def on_clear_log(self, _btn):
        self.log_buf.clear()
        self._notice("Log cleared.")

    def on_save_log(self, _btn):
        path = self._save_dialog("Save log", "zorin-optimizer.log")
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
        self.status_label.set_text("Simulate ON — no changes will be made" if enabled else "Ready")
        if enabled:
            self._notify("Simulate is ON. Actions are previewed in Logs only.", "info")

    def on_preferences(self, _btn):
        dialog = Gtk.Dialog(title="Preferences", parent=self, flags=0)
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
            values = {
                "default_source": "apt" if source_combo.get_active() == 1 else "flatpak",
                "auto_refresh_seconds": refresh_values[max(0, refresh_combo.get_active())],
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
                self._notify("Could not save preferences — check permissions on ~/.config.", "error")
        dialog.destroy()

    def on_help(self, _btn):
        self._show_dialog(
            "Quick start",
            "1. Turn on Simulate (top right) to preview actions safely.\n"
            "2. Dashboard shows what tools are available on your system.\n"
            "3. Install Apps: search, tick, then Install Selected.\n"
            "4. Manage Apps: update or remove what is already installed.\n"
            "5. Optimize System: only changed settings are applied.\n"
            "6. Logs shows every command and its result — save it before asking for help.\n\n"
            "Full guide: docs/USER_GUIDE.md in the repository.",
            Gtk.MessageType.INFO)

    def on_about(self, _btn):
        dialog = Gtk.AboutDialog(transient_for=self)
        dialog.set_program_name(APP_NAME)
        dialog.set_version("v" + __version__)
        dialog.set_comments("Safe app installs, cleanup and system tuning for Zorin OS.")
        dialog.set_website("https://github.com/mdadeel/ZorinOS-Optimizer")
        dialog.set_website_label("Project on GitHub")
        dialog.set_license("MIT")
        dialog.set_authors(["Zorin Optimizer contributors"])
        dialog.set_logo_icon_name("utilities-system-monitor")
        dialog.run()
        dialog.destroy()


class ZorinOptimizerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
