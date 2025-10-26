import os
import threading
import json
from typing import Dict, List

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .backend import utils
from .backend import apps as apps_backend
from .backend import system as system_backend
from .backend import performance as perf_backend
from .backend import ui_customization as ui_backend
from .backend import dashboard as dash_backend

APP_NAME = "Zorin Optimizer"


class LogBuffer:
    def __init__(self, textbuffer: Gtk.TextBuffer):
        self.buf = textbuffer

    def append(self, text: str):
        def _append():
            end = self.buf.get_end_iter()
            self.buf.insert(end, text)
            return False
        GLib.idle_add(_append)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(980, 680)

        hb = Gtk.HeaderBar(title=APP_NAME)
        hb.set_subtitle("MVP")
        hb.set_show_close_button(True)
        # Simulate switch
        self.sim_switch = Gtk.Switch()
        self.sim_switch.set_active(False)
        self.sim_switch.connect("state-set", self.on_toggle_simulate)
        hb.pack_end(Gtk.Label(label="Simulate"))
        hb.pack_end(self.sim_switch)
        self.set_titlebar(hb)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=250)
        sidebar = Gtk.StackSidebar(stack=self.stack)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(sidebar, False, False, 0)
        root.pack_start(self.stack, True, True, 0)
        self.add(root)

        # Logs view
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_buf = LogBuffer(self.log_view.get_buffer())

        # Pages
        self._build_install_page()
        self._build_manage_page()
        self._build_optimize_page()
        self._build_customize_page()
        self._build_backup_page()
        self._build_dashboard_page()
        self._build_logs_page()

        self.show_all()

    # ----- Install Page -----
    def _build_install_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        # Source toggle
        self.install_source = Gtk.ComboBoxText()
        self.install_source.append_text("Flatpak")
        self.install_source.append_text("APT")
        self.install_source.set_active(0)

        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="Install source:"), False, False, 0)
        top.pack_start(self.install_source, False, False, 0)
        box.pack_start(top, False, False, 0)

        # App list
        self.app_checks: Dict[str, Gtk.CheckButton] = {}
        self.app_status_labels: Dict[str, Gtk.Label] = {}
        self.apps_config = apps_backend.load_apps()
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        row = 0
        for cat, items in self.apps_config.items():
            lbl = Gtk.Label(label=f"{cat}")
            lbl.set_xalign(0)
            grid.attach(lbl, 0, row, 3, 1)
            row += 1
            for app in items:
                app_id = app.get("id")
                chk = Gtk.CheckButton.new_with_label(app.get("name", app_id))
                self.app_checks[app_id] = chk
                status_lbl = Gtk.Label(label="?")
                status_lbl.set_xalign(0)
                self.app_status_labels[app_id] = status_lbl
                grid.attach(chk, 1, row, 1, 1)
                grid.attach(status_lbl, 2, row, 1, 1)
                row += 1
        sc = Gtk.ScrolledWindow()
        sc.add(grid)
        box.pack_start(sc, True, True, 0)

        # Presets and refresh row
        presets_box = Gtk.Box(spacing=8)
        self.cmb_presets = Gtk.ComboBoxText()
        self.cmb_presets.append_text("Select preset…")
        try:
            import json, os
            from .backend import apps as _apps
            # Load presets file
            import_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "presets.json")
            with open(import_path, "r", encoding="utf-8") as f:
                self.presets = json.load(f)
            for name in self.presets.keys():
                self.cmb_presets.append_text(name)
            self.cmb_presets.set_active(0)
        except Exception:
            self.presets = {}
            self.cmb_presets.set_active(0)
        btn_apply_preset = Gtk.Button(label="Apply Preset")
        btn_apply_preset.connect("clicked", self.on_apply_preset)
        btn_refresh = Gtk.Button(label="Refresh Status")
        btn_refresh.connect("clicked", self.on_refresh_status)
        presets_box.pack_start(self.cmb_presets, False, False, 0)
        presets_box.pack_start(btn_apply_preset, False, False, 0)
        presets_box.pack_end(btn_refresh, False, False, 0)
        box.pack_start(presets_box, False, False, 0)

        # Buttons
        btn_box = Gtk.Box(spacing=8)
        btn_install = Gtk.Button(label="Install Selected")
        btn_update = Gtk.Button(label="Update All")
        btn_uninstall = Gtk.Button(label="Uninstall Selected")
        btn_install.connect("clicked", self.on_install_selected)
        btn_update.connect("clicked", self.on_update_all)
        btn_uninstall.connect("clicked", self.on_uninstall_selected)
        btn_box.pack_start(btn_install, False, False, 0)
        btn_box.pack_start(btn_update, False, False, 0)
        btn_box.pack_start(btn_uninstall, False, False, 0)
        box.pack_start(btn_box, False, False, 0)

        self.stack.add_titled(box, "install", "Install Apps")
        # initial status
        self.on_refresh_status(None)

    def _selected_apps(self) -> List[str]:
        return [aid for aid, chk in self.app_checks.items() if chk.get_active()]

    def on_install_selected(self, _btn):
        source = self.install_source.get_active_text().lower()
        app_ids = self._selected_apps()
        self._run_async(self._install_apps, source, app_ids)

    def on_update_all(self, _btn):
        source = self.install_source.get_active_text().lower()
        self._run_async(self._update_all, source)

    def on_uninstall_selected(self, _btn):
        source = self.install_source.get_active_text().lower()
        app_ids = self._selected_apps()
        self._run_async(self._uninstall_apps, source, app_ids)

    # ----- Optimize Page -----
    def _build_optimize_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        self.chk_cleanup = Gtk.CheckButton.new_with_label("Run cleanup (APT and Flatpak)")
        self.chk_animations = Gtk.CheckButton.new_with_label("Disable GNOME animations")
        self.chk_animations.set_active(False)

        self.chk_swap = Gtk.CheckButton.new_with_label("Enable swapfile (2G)")
        self.chk_zram = Gtk.CheckButton.new_with_label("Enable ZRAM (if supported)")

        power_box = Gtk.Box(spacing=8)
        power_box.pack_start(Gtk.Label(label="Power profile:"), False, False, 0)
        self.cmb_power = Gtk.ComboBoxText()
        for profile in ["balanced", "power-saver", "performance"]:
            self.cmb_power.append_text(profile)
        self.cmb_power.set_active(0)
        power_box.pack_start(self.cmb_power, False, False, 0)

        btn_run = Gtk.Button(label="Run Optimization")
        btn_run.connect("clicked", self.on_run_optimize)

        # Startup apps manager
        btn_startup = Gtk.Button(label="Manage Startup Apps…")
        btn_startup.connect("clicked", self.on_manage_startup)

        for w in (self.chk_cleanup, self.chk_animations, self.chk_swap, self.chk_zram, power_box, btn_run, btn_startup):
            box.pack_start(w, False, False, 0)

        self.stack.add_titled(box, "optimize", "Optimize System")

    def on_run_optimize(self, _btn):
        opts = {
            "cleanup": self.chk_cleanup.get_active(),
            "animations_off": self.chk_animations.get_active(),
            "swap": self.chk_swap.get_active(),
            "zram": self.chk_zram.get_active(),
            "power": self.cmb_power.get_active_text(),
        }
        self._run_async(self._optimize, opts)

    # ----- Backup & Restore Page -----
    def _build_backup_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        btn_snap = Gtk.Button(label="Create Timeshift Snapshot")
        btn_snap.connect("clicked", lambda _b: self._run_async(__import__('zorin_optim_tool.backend.backup', fromlist=['']).backup.timeshift_snapshot))
        btn_open_ts = Gtk.Button(label="Open Timeshift GUI")
        btn_open_ts.connect("clicked", lambda _b: self._run_async(__import__('zorin_optim_tool.backend.backup', fromlist=['']).backup.open_timeshift_gui))
        btn_export = Gtk.Button(label="Export ~/.config…")
        btn_export.connect("clicked", self.on_export_config)
        btn_import = Gtk.Button(label="Import ~/.config…")
        btn_import.connect("clicked", self.on_import_config)
        for w in (btn_snap, btn_open_ts, Gtk.Separator(), btn_export, btn_import):
            box.pack_start(w, False, False, 0)
        self.stack.add_titled(box, "backup", "Backup & Restore")

    def on_export_config(self, _btn):
        dialog = Gtk.FileChooserDialog(title="Save Config Archive", parent=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_name("config-backup.tar.xz")
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            from .backend import backup
            self._run_async(backup.export_configs, path)
        else:
            dialog.destroy()

    def on_import_config(self, _btn):
        dialog = Gtk.FileChooserDialog(title="Open Config Archive", parent=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            from .backend import backup
            self._run_async(backup.import_configs, path)
        else:
            dialog.destroy()

    # ----- Customize Page -----
    def _build_customize_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        self.cmb_theme = Gtk.ComboBoxText()
        self.cmb_theme.append_text("Light")
        self.cmb_theme.append_text("Dark")
        self.cmb_theme.set_active(0)

        btn_apply_theme = Gtk.Button(label="Apply Theme")
        btn_apply_theme.connect("clicked", self.on_apply_theme)

        btn_icon = Gtk.Button(label="Install Icon Pack (.tar.xz)")
        btn_icon.connect("clicked", self.on_install_icon)

        self.chk_round = Gtk.CheckButton.new_with_label("Rounded corners (user CSS)")

        for w in (
            Gtk.Label(label="Theme (light/dark):"), self.cmb_theme, btn_apply_theme,
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            btn_icon, self.chk_round,
        ):
            box.pack_start(w, False, False, 0)

        btn_apply_look = Gtk.Button(label="Apply Look Changes")
        btn_apply_look.connect("clicked", self.on_apply_look)
        box.pack_start(btn_apply_look, False, False, 0)

        self.stack.add_titled(box, "customize", "Customize Look")

    def on_apply_theme(self, _btn):
        mode = "dark" if self.cmb_theme.get_active_text().lower() == "dark" else "light"
        self._run_async(ui_backend.apply_theme_mode, mode)

    def on_install_icon(self, _btn):
        dialog = Gtk.FileChooserDialog(title="Select Icon Pack (.tar.xz)", parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name("Tarballs")
        filt.add_pattern("*.tar.xz")
        dialog.add_filter(filt)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            self._run_async(ui_backend.install_icon_pack, path)
        else:
            dialog.destroy()

    def on_apply_look(self, _btn):
        round_on = self.chk_round.get_active()
        self._run_async(ui_backend.set_rounded_corners, round_on)

    # ----- Manage Installed Page -----
    def _build_manage_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        self.manage_listbox = Gtk.ListBox()
        sc = Gtk.ScrolledWindow()
        sc.add(self.manage_listbox)
        box.pack_start(sc, True, True, 0)
        btn_row = Gtk.Box(spacing=8)
        btn_refresh = Gtk.Button(label="Scan Installed")
        btn_uninstall = Gtk.Button(label="Uninstall Selected")
        btn_refresh.connect("clicked", self.on_scan_installed)
        btn_uninstall.connect("clicked", self.on_uninstall_scanned)
        btn_row.pack_start(btn_refresh, False, False, 0)
        btn_row.pack_start(btn_uninstall, False, False, 0)
        box.pack_start(btn_row, False, False, 0)
        self.stack.add_titled(box, "manage", "Manage Apps")
        self.on_scan_installed(None)

    def on_scan_installed(self, _btn):
        # Safely clear existing rows
        for row in list(self.manage_listbox.get_children()):
            self.manage_listbox.remove(row)
        def worker():
            from .backend import apps as ap
            flatpaks = ap.list_installed_flatpak()
            apts = ap.list_installed_apt()
            entries = flatpaks + apts
            def add_rows():
                for it in entries:
                    row = Gtk.ListBoxRow()
                    h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                    chk = Gtk.CheckButton()
                    lbl = Gtk.Label(label=f"{it['name']} ({it['source']})")
                    lbl.set_xalign(0)
                    h.pack_start(chk, False, False, 0)
                    h.pack_start(lbl, True, True, 0)
                    row.add(h)
                    row.it = it
                    row.chk = chk
                    self.manage_listbox.add(row)
                self.manage_listbox.show_all()
            GLib.idle_add(add_rows)
        threading.Thread(target=worker, daemon=True).start()

    def on_uninstall_scanned(self, _btn):
        rows = self.manage_listbox.get_children()
        selected = []
        for r in rows:
            if getattr(r, 'chk', None) and r.chk.get_active():
                selected.append(r.it)
        if not selected:
            return
        from .backend import apps as ap
        self._run_async(ap.uninstall_installed, selected)

    # ----- Dashboard Page -----
    def _build_dashboard_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)

        self.lbl_stats = Gtk.Label(label="Loading stats…")
        btn_refresh = Gtk.Button(label="Refresh")
        btn_refresh.connect("clicked", lambda _b: self._run_async(self._refresh_stats))
        btn_cleanup = Gtk.Button(label="Run Cleanup Now")
        btn_cleanup.connect("clicked", lambda _b: self._run_async(system_backend.run_cleanup, self.log_buf))

        for w in (self.lbl_stats, btn_refresh, btn_cleanup):
            box.pack_start(w, False, False, 0)

        self.stack.add_titled(box, "dashboard", "System Dashboard")
        self._run_async(self._refresh_stats)

    def _refresh_stats(self):
        info = dash_backend.get_system_info()
        text = (
            f"CPU: {info['cpu_percent']}% | RAM: {info['mem_percent']}% | Disk: {info['disk_percent']}%\n"
            f"OS: {info['os']} | Kernel: {info['kernel']} | Uptime: {info['uptime']}\n"
        )
        self.log_buf.append("[dashboard] stats refreshed\n")
        def _set():
            self.lbl_stats.set_text(text)
        GLib.idle_add(_set)

    # ----- Logs Page -----
    def _build_logs_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sc = Gtk.ScrolledWindow()
        sc.add(self.log_view)
        box.pack_start(sc, True, True, 0)
        self.stack.add_titled(box, "logs", "Logs")

    # ----- Backend actions (run in threads) -----
    def _run_async(self, func, *args):
        def target():
            try:
                func(*args, log=self.log_buf)
            except TypeError:
                # Fallback if func does not accept log
                result = func(*args)
                if result is not None:
                    self.log_buf.append(str(result) + "\n")
            except Exception as e:
                self.log_buf.append(f"[error] {e}\n")
        threading.Thread(target=target, daemon=True).start()

    # UI callbacks
    def on_toggle_simulate(self, switch, state):
        from .backend.utils import set_simulate
        set_simulate(bool(state))
        self.log_buf.append(f"[simulate] {'ON' if state else 'OFF'}\n")
        return False

    def on_refresh_status(self, _btn):
        source = self.install_source.get_active_text().lower()
        status = apps_backend.get_status_map(source)
        for aid, lbl in self.app_status_labels.items():
            inst = status.get(aid, False)
            lbl.set_text("Installed" if inst else "Not installed")

    def on_apply_preset(self, _btn):
        idx = self.cmb_presets.get_active()
        if idx <= 0:
            return
        name = self.cmb_presets.get_active_text()
        app_ids = self.presets.get(name, [])
        for aid, chk in self.app_checks.items():
            chk.set_active(aid in app_ids)

    # Installer helpers
    def _install_apps(self, source: str, app_ids: List[str], log: LogBuffer):
        utils.ensure_flathub()
        apps_backend.install_apps(app_ids, source, log)
        self.on_refresh_status(None)

    def _update_all(self, source: str, log: LogBuffer):
        apps_backend.update_all(source, log)
        self.on_refresh_status(None)

    def _uninstall_apps(self, source: str, app_ids: List[str], log: LogBuffer):
        apps_backend.uninstall_apps(app_ids, source, log)
        self.on_refresh_status(None)

    def _optimize(self, opts: Dict, log: LogBuffer):
        if opts.get("cleanup"):
            system_backend.run_cleanup(log)
        system_backend.set_animations(enabled=not opts.get("animations_off", False), log=log)
        if opts.get("power"):
            perf_backend.set_power_profile(opts["power"], log)
        if opts.get("swap"):
            perf_backend.enable_swapfile(size_gb=2, log=log)
        else:
            perf_backend.disable_swapfile(log)
        if opts.get("zram"):
            perf_backend.enable_zram(log)
        else:
            perf_backend.disable_zram(log)

    def on_manage_startup(self, _btn):
        # Dialog listing startup apps with toggles
        dialog = Gtk.Dialog(title="Startup Applications", parent=self, flags=0)
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        box = dialog.get_content_area()
        sc = Gtk.ScrolledWindow()
        box.add(sc)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sc.add(vbox)
        items = system_backend.list_startup_apps()
        toggle_widgets = []
        for it in items:
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label=it["name"])
            lbl.set_xalign(0)
            sw = Gtk.Switch()
            sw.set_active(not it["hidden"])
            row.pack_start(lbl, True, True, 0)
            row.pack_end(sw, False, False, 0)
            vbox.pack_start(row, False, False, 0)
            toggle_widgets.append((sw, it))
        vbox.show_all()

        def on_response(_d, resp):
            if resp == Gtk.ResponseType.CLOSE:
                for sw, it in toggle_widgets:
                    system_backend.set_startup_app(it["path"], sw.get_active(), log=self.log_buf)
                dialog.destroy()
        dialog.connect("response", on_response)
        dialog.show_all()


class ZorinOptimizerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.example.zorinoptimizer")

    def do_activate(self):
        win = MainWindow(self)
        win.present()


def main():
    app = ZorinOptimizerApp()
    app.run(None)


if __name__ == "__main__":
    main()
