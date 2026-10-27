"""GTK 3 user interface.

Threading contract: backend work runs in daemon threads, and *every* widget
mutation goes through ``GLib.idle_add``. Operations are serialised so a user
cannot fire five simultaneous pkexec prompts by double-clicking Install.
"""
from __future__ import annotations

import threading
import traceback

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from . import __version__  # noqa: E402
from .backend import (  # noqa: E402
    apps as apps_backend,
    backup as backup_backend,
    dashboard as dash_backend,
    performance as perf_backend,
    system as system_backend,
    ui_customization as ui_backend,
    utils,
)

APP_NAME = "Zorin Optimizer"
APP_ID = "io.github.mdadeel.ZorinOptimizer"
MAX_LOG_LINES = 4000


class LogBuffer:
    """Thread-safe append-only log with an in-memory copy for saving."""

    def __init__(self, textbuffer: Gtk.TextBuffer, textview: Gtk.TextView):
        self.buf = textbuffer
        self.view = textview
        self.lines = []
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
        self.set_default_size(1060, 720)
        self._busy = False
        self._busy_lock = threading.Lock()
        self.action_widgets = []
        # Sensible defaults so the first "Run Optimization" cannot apply an
        # unintended power/swap change before the async state read finishes.
        self.baseline = {
            "animations_off": False, "swap": False, "zram": False,
            "power": "balanced", "theme": "light", "round": False,
        }
        self.app_rows = {}

        # ----- Header -----
        header = Gtk.HeaderBar(title=APP_NAME, subtitle="v" + __version__)
        header.set_show_close_button(True)
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.set_xalign(0)
        header.pack_start(self.status_label)

        sim_box = Gtk.Box(spacing=6)
        self.sim_switch = Gtk.Switch()
        self.sim_switch.set_tooltip_text("Dry-run: log every action without changing the system")
        self.sim_switch.connect("notify::active", self.on_toggle_simulate)
        sim_box.pack_start(Gtk.Label(label="Simulate"), False, False, 0)
        sim_box.pack_start(self.sim_switch, False, False, 0)
        header.pack_end(sim_box)
        self.set_titlebar(header)

        # ----- Layout -----
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=200)
        sidebar = Gtk.StackSidebar(stack=self.stack)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(sidebar, False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.add(root)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_buf = LogBuffer(self.log_view.get_buffer(), self.log_view)

        self._build_install_page()
        self._build_manage_page()
        self._build_optimize_page()
        self._build_customize_page()
        self._build_backup_page()
        self._build_dashboard_page()
        self._build_logs_page()

        self.show_all()
        self.log_buf.append("[info] Zorin Optimizer {} started. Simulate is {}.\n".format(
            __version__, "ON" if utils.is_simulate() else "OFF"))
        self._start_initial_tasks()

    # ------------------------------------------------------------------
    # Task runner
    # ------------------------------------------------------------------
    def _button(self, label, callback, tooltip=None):
        button = Gtk.Button(label=label)
        button.connect("clicked", callback)
        if tooltip:
            button.set_tooltip_text(tooltip)
        self.action_widgets.append(button)
        return button

    def submit(self, func, *args, done=None):
        """Run a backend function in a worker thread, then call ``done`` on the UI thread."""
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
            self.status_label.set_text(result.message)
            for detail in result.details:
                self.log_buf.append("    - " + detail + "\n")
            if not result.ok:
                self._show_dialog("Action failed", result.message + "\n\n" + "\n".join(result.details),
                                  Gtk.MessageType.ERROR)
        if done is not None:
            try:
                done(result)
            except Exception as exc:
                self.log_buf.append("[error] UI update failed: {}\n".format(exc))
        return False

    def _start_initial_tasks(self):
        # Tasks are serialised, so chain the four startup reads instead of
        # firing four submits (three of which would be rejected as "busy").
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
        GLib.timeout_add_seconds(15, self._periodic_refresh)

    def _periodic_refresh(self):
        with self._busy_lock:
            busy = self._busy
        if not busy:
            self.submit(dash_backend.get_system_info, done=self._apply_stats)
        return True

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------
    def _show_dialog(self, title, message, kind=Gtk.MessageType.INFO):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=kind,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        if message:
            dialog.format_secondary_text(message[:2000])
        dialog.run()
        dialog.destroy()

    def _confirm(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self, flags=0,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=title)
        dialog.format_secondary_text(message[:2000])
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _notice(self, message):
        self.status_label.set_text(message)
        self.log_buf.append("[notice] " + message + "\n")

    # ------------------------------------------------------------------
    # Install page
    # ------------------------------------------------------------------
    def _build_install_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Preferred source:"), False, False, 0)
        self.install_source = Gtk.ComboBoxText()
        for text in ("Flatpak", "APT"):
            self.install_source.append_text(text)
        self.install_source.set_active(0)
        self.install_source.connect("changed", lambda _c: self.on_refresh_status(None))
        top.pack_start(self.install_source, False, False, 0)
        self.install_search = Gtk.SearchEntry()
        self.install_search.set_placeholder_text("Filter apps…")
        self.install_search.set_hexpand(True)
        self.install_search.connect("search-changed",
                                    lambda _e: self.install_list.invalidate_filter())
        top.pack_start(self.install_search, True, True, 0)
        box.pack_start(top, False, False, 0)

        self.install_list = Gtk.ListBox()
        self.install_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.install_list.set_filter_func(self._install_filter, None)
        for category, items in apps_backend.load_apps().items():
            header_row = Gtk.ListBoxRow()
            header_row.set_activatable(False)
            header_row.is_header = True
            header_label = Gtk.Label(label=category)
            header_label.set_xalign(0)
            header_label.set_markup("<b>" + _escape_markup(category) + "</b>")
            header_row.add(header_label)
            self.install_list.add(header_row)
            for item in items:
                app_id = item["id"]
                row = Gtk.ListBoxRow()
                row.is_header = False
                row.app_id = app_id
                row.search_text = (item["name"] + " " + category + " " + app_id).lower()
                line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                chk = Gtk.CheckButton()
                name = Gtk.Label(label=item["name"])
                name.set_xalign(0)
                name.set_hexpand(True)
                badge = Gtk.Label(label=self._source_badge(item))
                badge.set_tooltip_text(item.get("note", ""))
                status = Gtk.Label(label="…")
                status.set_width_chars(22)
                status.set_xalign(0)
                for widget in (chk, name, badge, status):
                    line.pack_start(widget, False if widget is chk else True, True, 0)
                row.add(line)
                row.chk = chk
                row.status_label = status
                self.app_rows[app_id] = row
                self.install_list.add(row)

        scroll = Gtk.ScrolledWindow()
        scroll.add(self.install_list)
        box.pack_start(scroll, True, True, 0)

        preset_row = Gtk.Box(spacing=8)
        self.cmb_presets = Gtk.ComboBoxText()
        self.cmb_presets.append_text("Select preset…")
        self.presets = apps_backend.load_presets()
        for name in self.presets:
            self.cmb_presets.append_text(name)
        self.cmb_presets.set_active(0)
        preset_row.pack_start(self.cmb_presets, False, False, 0)
        preset_row.pack_start(self._button("Apply Preset", self.on_apply_preset), False, False, 0)
        preset_row.pack_end(self._button("Refresh Status", self.on_refresh_status), False, False, 0)
        box.pack_start(preset_row, False, False, 0)

        buttons = Gtk.Box(spacing=8)
        buttons.pack_start(self._button("Install Selected", self.on_install_selected,
                                        "Install checked apps (respects Simulate mode)"), False, False, 0)
        buttons.pack_start(self._button("Update Selected", self.on_update_selected), False, False, 0)
        buttons.pack_start(self._button("Update All", self.on_update_all), False, False, 0)
        buttons.pack_start(self._button("Uninstall Selected", self.on_uninstall_selected), False, False, 0)
        box.pack_start(buttons, False, False, 0)

        self.stack.add_titled(box, "install", "Install Apps")

    @staticmethod
    def _source_badge(item):
        has_flat, has_apt = bool(item.get("flatpak")), bool(item.get("apt"))
        if has_flat and has_apt:
            return "Flatpak + APT"
        return "Flatpak" if has_flat else "APT"

    def _install_filter(self, row, _data):
        query = self.install_search.get_text().strip().lower()
        if getattr(row, "is_header", False):
            return not query
        return not query or query in getattr(row, "search_text", "")

    def _source(self):
        return (self.install_source.get_active_text() or "Flatpak").lower()

    def _selected_apps(self):
        return [app_id for app_id, row in self.app_rows.items() if row.chk.get_active()]

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

    def on_apply_preset(self, _btn):
        name = self.cmb_presets.get_active_text()
        app_ids = self.presets.get(name, [])
        if name == "Select preset…" or not app_ids:
            self._notice("Choose a preset first.")
            return
        for app_id, row in self.app_rows.items():
            row.chk.set_active(app_id in app_ids)
        self._notice("Preset '{}' selected {} app(s).".format(name, len(app_ids)))

    def on_install_selected(self, _btn):
        app_ids = self._selected_apps()
        if not app_ids:
            self._notice("Tick at least one app first.")
            return
        self.submit(apps_backend.install_apps, app_ids, self._source(),
                    done=lambda _r: self.on_refresh_status())

    def on_update_selected(self, _btn):
        app_ids = self._selected_apps()
        if not app_ids:
            self._notice("Tick at least one app first.")
            return
        self.submit(apps_backend.update_apps, app_ids, self._source(),
                    done=lambda _r: self.on_refresh_status())

    def on_uninstall_selected(self, _btn):
        app_ids = self._selected_apps()
        if not app_ids:
            self._notice("Tick at least one app first.")
            return
        if not self._confirm("Uninstall {} app(s)?".format(len(app_ids)),
                             "This removes the installed APT/Flatpak packages for the selected apps."):
            return
        self.submit(apps_backend.uninstall_apps, app_ids, self._source(),
                    done=lambda _r: self.on_refresh_status())

    def on_update_all(self, _btn):
        source = self._source()
        if not self._confirm("Update all {} packages?".format(source.upper()),
                             "This runs a full {} update and may take several minutes.".format(source)):
            return
        self.submit(apps_backend.update_all, source,
                    done=lambda _r: self.on_refresh_status())

    # ------------------------------------------------------------------
    # Manage page
    # ------------------------------------------------------------------
    def _build_manage_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        top = Gtk.Box(spacing=8)
        self.manage_search = Gtk.SearchEntry()
        self.manage_search.set_placeholder_text("Filter installed apps…")
        self.manage_search.set_hexpand(True)
        self.manage_search.connect("search-changed",
                                   lambda _e: self.manage_listbox.invalidate_filter())
        top.pack_start(self.manage_search, True, True, 0)
        top.pack_start(self._button("Scan Installed", self.on_scan_installed), False, False, 0)
        box.pack_start(top, False, False, 0)

        self.manage_listbox = Gtk.ListBox()
        self.manage_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.manage_listbox.set_filter_func(self._manage_filter, None)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.manage_listbox)
        box.pack_start(scroll, True, True, 0)

        row = Gtk.Box(spacing=8)
        row.pack_start(self._button("Update Selected", self.on_update_scanned), False, False, 0)
        row.pack_start(self._button("Uninstall Selected", self.on_uninstall_scanned), False, False, 0)
        hint = Gtk.Label(label="Core system packages are locked to protect your desktop.")
        hint.set_xalign(1)
        hint.set_hexpand(True)
        row.pack_end(hint, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.stack.add_titled(box, "manage", "Manage Apps")

    @staticmethod
    def _scan_installed_worker():
        return apps_backend.list_installed_flatpak() + apps_backend.list_installed_apt()

    def _manage_filter(self, row, _data):
        query = self.manage_search.get_text().strip().lower()
        if isinstance(row, Gtk.Label) or not hasattr(row, "search_text"):
            return True
        return not query or query in row.search_text

    def on_scan_installed(self, _btn=None):
        self.submit(self._scan_installed_worker, done=self._fill_manage_rows)

    def _fill_manage_rows(self, entries):
        if not isinstance(entries, list):
            return
        for row in list(self.manage_listbox.get_children()):
            self.manage_listbox.remove(row)
        for entry in sorted(entries, key=lambda e: (e["source"], e["name"].lower())):
            row = Gtk.ListBoxRow()
            row.entry = entry
            row.search_text = (entry["name"] + " " + entry["id"] + " " + entry["source"]).lower()
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            chk = Gtk.CheckButton()
            chk.set_sensitive(not entry.get("protected"))
            label = Gtk.Label(label="{}  ·  {}".format(entry["name"], entry["source"]))
            label.set_xalign(0)
            label.set_hexpand(True)
            line.pack_start(chk, False, False, 0)
            line.pack_start(label, True, True, 0)
            if entry.get("protected"):
                line.pack_start(Gtk.Label(label="🔒 protected"), False, False, 0)
            row.add(line)
            row.chk = chk
            self.manage_listbox.add(row)
        self.manage_listbox.show_all()
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
            self._notice("Tick at least one installed app first.")
            return
        if not self._confirm("Uninstall {} package(s)?".format(len(selected)),
                             "\n".join("• {} ({})".format(e["name"], e["source"]) for e in selected)):
            return
        self.submit(apps_backend.uninstall_installed, selected,
                    done=lambda _r: self.on_scan_installed())

    def on_update_scanned(self, _btn):
        selected = self._selected_manage()
        if not selected:
            self._notice("Tick at least one installed app first.")
            return
        self.submit(apps_backend.update_installed, selected)

    # ------------------------------------------------------------------
    # Optimize page
    # ------------------------------------------------------------------
    def _build_optimize_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.chk_cleanup = Gtk.CheckButton.new_with_label("Run cleanup (APT autoremove/autoclean + Flatpak unused)")
        self.chk_animations = Gtk.CheckButton.new_with_label("Disable GNOME animations")
        self.chk_swap = Gtk.CheckButton.new_with_label("Enable 2 GB swapfile")
        self.chk_zram = Gtk.CheckButton.new_with_label("Enable ZRAM (requires systemd-zram-generator)")

        power_box = Gtk.Box(spacing=8)
        power_box.pack_start(Gtk.Label(label="Power profile:"), False, False, 0)
        self.cmb_power = Gtk.ComboBoxText()
        for profile in perf_backend.POWER_PROFILES:
            self.cmb_power.append_text(profile)
        self.cmb_power.set_active(0)
        power_box.pack_start(self.cmb_power, False, False, 0)

        note = Gtk.Label(label="Only settings you changed are applied; nothing else is touched.")
        note.set_xalign(0)
        for widget in (self.chk_cleanup, self.chk_animations, self.chk_swap,
                       self.chk_zram, power_box,
                       self._button("Run Optimization", self.on_run_optimize),
                       self._button("Manage Startup Apps…", self.on_manage_startup),
                       note):
            box.pack_start(widget, False, False, 0)
        self.stack.add_titled(box, "optimize", "Optimize System")

    def _read_settings(self):
        return {
            "animations_off": not system_backend.are_animations_enabled(),
            "swap": perf_backend.is_swapfile_active(),
            "zram": perf_backend.is_zram_active() or perf_backend.is_zram_configured(),
            "power": perf_backend.get_power_profile() or "balanced",
            "theme": ui_backend.get_theme_mode(),
            "round": ui_backend.are_rounded_corners_enabled(),
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
            self._notice("No changes requested — settings already match.")
            return
        self.submit(utils.run_actions, actions, done=lambda _r: self._refresh_settings())

    def on_manage_startup(self, _btn):
        items = system_backend.list_startup_apps()
        if not items:
            self._notice("No autostart entries found.")
            return
        dialog = Gtk.Dialog(title="Startup Applications", parent=self, flags=0)
        dialog.set_default_size(520, 460)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_APPLY, Gtk.ResponseType.APPLY)
        scroll = Gtk.ScrolledWindow()
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_border_width(8)
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
        actions = []
        for enabled, item in changes:
            actions.append(("Startup: " + item["name"], system_backend.set_startup_app,
                            (item["path"], enabled)))
        self.submit(utils.run_actions, actions)

    # ------------------------------------------------------------------
    # Customize page
    # ------------------------------------------------------------------
    def _build_customize_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Theme:"), False, False, 0)
        self.cmb_theme = Gtk.ComboBoxText()
        self.cmb_theme.append_text("Light")
        self.cmb_theme.append_text("Dark")
        self.cmb_theme.set_active(0)
        row.pack_start(self.cmb_theme, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.chk_round = Gtk.CheckButton.new_with_label("Rounded corners (user gtk.css)")
        box.pack_start(self.chk_round, False, False, 0)
        box.pack_start(self._button("Apply Theme", self.on_apply_theme), False, False, 0)
        box.pack_start(self._button("Install Icon Pack (.tar.xz/.tar.gz)", self.on_install_icon),
                       False, False, 0)
        box.pack_start(self._button("Apply Look Changes", self.on_apply_look), False, False, 0)
        self.stack.add_titled(box, "customize", "Customize Look")

    def on_apply_theme(self, _btn):
        mode = "dark" if (self.cmb_theme.get_active_text() or "Light").lower() == "dark" else "light"
        self.submit(ui_backend.apply_theme_mode, mode, done=lambda _r: self._refresh_settings())

    def on_apply_look(self, _btn):
        mode = "dark" if (self.cmb_theme.get_active_text() or "Light").lower() == "dark" else "light"
        actions = []
        if mode != self.baseline.get("theme"):
            actions.append(("Theme", ui_backend.apply_theme_mode, (mode,)))
        if self.chk_round.get_active() != self.baseline.get("round"):
            actions.append(("Rounded corners", ui_backend.set_rounded_corners,
                            (self.chk_round.get_active(),)))
        if not actions:
            self._notice("No look changes requested.")
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
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        box.pack_start(self._button("Create Timeshift Snapshot", self.on_snapshot), False, False, 0)
        box.pack_start(self._button("Open Timeshift GUI", self.on_open_timeshift), False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 0)
        box.pack_start(self._button("Export ~/.config…", self.on_export_config), False, False, 0)
        box.pack_start(self._button("Import ~/.config…", self.on_import_config), False, False, 0)
        note = Gtk.Label(label="Import only restores paths inside ~/.config and refuses links/traversal.")
        note.set_xalign(0)
        box.pack_start(note, False, False, 0)
        self.stack.add_titled(box, "backup", "Backup & Restore")

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
        path = self._save_dialog("Save config archive", "zorin-config-backup.tar.xz")
        if path:
            self.submit(backup_backend.export_configs, path)

    def on_import_config(self, _btn):
        path = self._open_dialog("Open config archive")
        if not path:
            return
        safe_count, unsafe = backup_backend.inspect_archive(path)
        if safe_count == 0:
            self._show_dialog("Cannot import", "Archive is empty, unreadable, or contains only unsafe entries.",
                              Gtk.MessageType.ERROR)
            return
        message = "This will overwrite files in ~/.config with {} item(s) from the archive.".format(safe_count)
        if unsafe:
            message += "\n\n{} unsafe entr(ies) will be refused: {}".format(
                len(unsafe), ", ".join(unsafe[:5]))
        if not self._confirm("Restore configuration?", message):
            return
        self.submit(backup_backend.import_configs, path)

    # ------------------------------------------------------------------
    # Dashboard & logs
    # ------------------------------------------------------------------
    def _build_dashboard_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.lbl_stats = Gtk.Label(label="Loading stats…")
        self.lbl_stats.set_xalign(0)
        self.lbl_stats.set_justify(Gtk.Justification.LEFT)
        box.pack_start(self.lbl_stats, False, False, 0)
        row = Gtk.Box(spacing=8)
        row.pack_start(self._button("Refresh", self._refresh_stats), False, False, 0)
        row.pack_start(self._button("Run Cleanup Now", self.on_dashboard_cleanup), False, False, 0)
        box.pack_start(row, False, False, 0)
        self.stack.add_titled(box, "dashboard", "System Dashboard")

    def _refresh_stats(self, _btn=None):
        self.submit(dash_backend.get_system_info, done=self._apply_stats)

    def _apply_stats(self, info):
        if not isinstance(info, dict):
            return
        self.lbl_stats.set_text(
            "CPU {cpu_percent}%  ·  {cpu_cores} cores\n"
            "RAM {mem_percent}%  ·  {mem_used}\n"
            "Disk {disk_percent}%  ·  {disk_used}\n"
            "OS: {os}\nKernel: {kernel}  ·  Uptime: {uptime}\n"
            "Power profile: {power_profile}".format(
                **{key: info.get(key, "?") for key in
                   ("cpu_percent", "cpu_cores", "mem_percent", "mem_used", "disk_percent",
                    "disk_used", "os", "kernel", "uptime", "power_profile")}))

    def on_dashboard_cleanup(self, _btn):
        if self._confirm("Run system cleanup?",
                         "Runs apt autoremove/autoclean and removes unused Flatpak runtimes."):
            self.submit(system_backend.run_cleanup)

    def _build_logs_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(12)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.log_view)
        box.pack_start(scroll, True, True, 0)
        row = Gtk.Box(spacing=8)
        save = Gtk.Button(label="Save Log…")
        save.connect("clicked", self.on_save_log)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda _b: self.log_buf.clear())
        row.pack_start(save, False, False, 0)
        row.pack_start(clear, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.stack.add_titled(box, "logs", "Logs")

    def on_save_log(self, _btn):
        path = self._save_dialog("Save log", "zorin-optimizer.log")
        if path:
            if self.log_buf.save(path):
                self._notice("Log saved.")
            else:
                self._show_dialog("Save failed", "Could not write {}".format(path), Gtk.MessageType.ERROR)

    # ------------------------------------------------------------------
    def on_toggle_simulate(self, switch, _param):
        enabled = switch.get_active()
        utils.set_simulate(enabled)
        self.log_buf.append("[simulate] {}\n".format("ON" if enabled else "OFF"))
        self.status_label.set_text("Simulate ON" if enabled else "Ready")


def _escape_markup(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class ZorinOptimizerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
