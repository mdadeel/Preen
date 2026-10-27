"""Cleanup, GNOME animations and startup-application management."""
from __future__ import annotations

import os
from typing import Dict, List

from . import utils
from .utils import Outcome, Report, fail, format_cmd, has_command, is_simulate, ok, run_cmd

AUTOSTART_DIRS = [
    os.path.expanduser("~/.config/autostart"),
    "/etc/xdg/autostart",
]


def run_cleanup(log=None) -> Outcome:
    """One polkit prompt for APT cleanup, one command for Flatpak."""
    report = Report(log)
    script = " && ".join([
        "DEBIAN_FRONTEND=noninteractive " + format_cmd(["apt-get", "autoremove", "-y"]),
        "DEBIAN_FRONTEND=noninteractive " + format_cmd(["apt-get", "autoclean", "-y"]),
    ])
    report.run(["bash", "-c", script], use_pkexec=True, mutate=True,
               timeout=utils.DEFAULT_TIMEOUT)
    if has_command("flatpak"):
        report.run(["flatpak", "uninstall", "--unused", "-y", "--noninteractive"],
                   mutate=True, timeout=utils.DEFAULT_TIMEOUT)
    else:
        report.note("[cleanup] flatpak not installed; skipping unused runtimes")
    return report.finish("Cleanup finished.", "Cleanup finished with errors")


# ---------------------------------------------------------------------------
# Animations
# ---------------------------------------------------------------------------
def are_animations_enabled() -> bool:
    if not has_command("gsettings"):
        return True
    result = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"])
    if not result.ok:
        return True
    return result.out.strip().lower() in ("true", "'true'")


def set_animations(enabled: bool, log=None) -> Outcome:
    state = "true" if enabled else "false"
    if not has_command("gsettings"):
        return fail("gsettings is not available; cannot change animations.")
    if is_simulate():
        if log:
            log.append("[simulate] would set enable-animations to {}\n".format(state))
        return ok("Would set animations to {}.".format(state))
    result = run_cmd(["gsettings", "set", "org.gnome.desktop.interface",
                      "enable-animations", state], mutate=True, log=log)
    if not result.ok:
        return fail("Could not change animations: {}".format(result.detail()))
    return ok("Animations {}.".format("enabled" if enabled else "disabled"))


# ---------------------------------------------------------------------------
# Startup applications
# ---------------------------------------------------------------------------
def list_startup_apps() -> List[Dict]:
    """Merge system entries with user overrides (user wins, no duplicates)."""
    by_name: Dict[str, Dict] = {}
    for directory in AUTOSTART_DIRS:
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for filename in names:
            if not filename.endswith(".desktop"):
                continue
            path = os.path.join(directory, filename)
            if not os.path.isfile(path):
                continue
            info = utils.parse_desktop_file(path)
            if str(info["type"]).lower() != "application" and not info["exec"]:
                continue
            hidden = bool(info["hidden"])
            if info["autostart_enabled"] is False:
                hidden = True
            entry = {
                "name": str(info["name"]),
                "hidden": hidden,
                "enabled": not hidden,
                "path": path,
                "user_owned": directory == AUTOSTART_DIRS[0],
            }
            # user overrides always win; otherwise first directory wins
            if filename not in by_name or entry["user_owned"]:
                by_name[filename] = entry
    return sorted(by_name.values(), key=lambda x: x["name"].lower())


def set_startup_app(path: str, enabled: bool, log=None) -> Outcome:
    """Enable/disable an autostart entry via a per-user override."""
    if not os.path.isfile(path):
        return fail("Desktop entry no longer exists: {}".format(path))
    user_dir = AUTOSTART_DIRS[0]
    user_path = os.path.join(user_dir, os.path.basename(path))
    verb = "enable" if enabled else "disable"

    if is_simulate():
        if log:
            log.append("[simulate] would {} {}\n".format(verb, os.path.basename(path)))
        return ok("Would {} {}.".format(verb, os.path.basename(path)))
    try:
        os.makedirs(user_dir, exist_ok=True)
        if not os.path.exists(user_path):
            with open(path, "r", encoding="utf-8", errors="ignore") as src:
                content = src.read()
            with open(user_path, "w", encoding="utf-8") as dst:
                dst.write(content)
        success = utils.set_autostart_hidden(user_path, hidden=not enabled)
    except OSError as exc:
        return fail("Could not {} {}: {}".format(verb, os.path.basename(path), exc))

    if not success:
        return fail("Could not write {}".format(user_path))
    if log:
        log.append("[autostart] {} {} -> {}\n".format(verb, os.path.basename(path), user_path))
    return ok("{} {}: ok.".format(verb.capitalize(), os.path.basename(path)))
