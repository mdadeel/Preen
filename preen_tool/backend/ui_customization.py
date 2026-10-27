"""Light/dark theme, icon packs and rounded-corner CSS.

Everything here used to bypass Simulate mode and write files even during a
"dry run". Icon pack extraction also used a bare ``tar.extractall`` (path
traversal) and guessed the theme name from directory mtimes.
"""
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from typing import List, Optional, Set

from . import utils
from .utils import Outcome, fail, has_command, is_simulate, ok, run_cmd

CSS_DIR = os.path.expanduser("~/.config/gtk-3.0")
CSS_PATH = os.path.join(CSS_DIR, "gtk.css")
START_GUARD = "/* BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
END_GUARD = "/* END ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
CSS_RULE = "window, dialog, .background { border-radius: 10px; }\n"


def _theme_roots() -> List[str]:
    return [
        "/usr/share/themes",
        os.path.expanduser("~/.themes"),
        os.path.expanduser("~/.local/share/themes"),
    ]


def _installed_themes() -> Set[str]:
    themes: Set[str] = set()
    for root in _theme_roots():
        try:
            themes.update(
                name for name in os.listdir(root)
                if os.path.isdir(os.path.join(root, name))
            )
        except OSError:
            continue
    return themes


def _current_gtk_theme() -> str:
    if not has_command("gsettings"):
        return ""
    result = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"], quiet=True)
    return result.out.strip().strip("'\"") if result.ok else ""


def get_theme_mode() -> str:
    if not has_command("gsettings"):
        return "light"
    result = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], quiet=True)
    value = result.out.strip().strip("'\"").lower()
    if value == "prefer-dark":
        return "dark"
    if value == "default":
        return "light"
    return "dark" if _current_gtk_theme().lower().endswith("dark") else "light"


def _pick_theme(mode: str) -> Optional[str]:
    """Only ever return a theme that really exists on disk."""
    installed = _installed_themes()
    current = _current_gtk_theme()
    if mode == "dark":
        candidates = [current, current + "-dark", current + "-Dark",
                      "Yaru-dark", "Adwaita-dark", "ZorinBlue-Dark", "HighContrast"]
        wanted = lambda name: "dark" in name.lower()  # noqa: E731
    else:
        candidates = [current, current.replace("-dark", "").replace("-Dark", ""),
                      "Yaru", "Adwaita", "ZorinBlue-Light"]
        wanted = lambda name: "dark" not in name.lower()  # noqa: E731
    if current in installed and wanted(current):
        return current
    for candidate in candidates:
        if candidate and candidate in installed and wanted(candidate):
            return candidate
    return None


def apply_theme_mode(mode: str, log=None) -> Outcome:
    mode = (mode or "light").lower()
    if mode not in ("light", "dark"):
        return fail("Unknown theme mode {!r}.".format(mode))
    if not has_command("gsettings"):
        return fail("gsettings is not available.")
    value = "prefer-dark" if mode == "dark" else "default"
    if is_simulate():
        if log:
            log.append("[simulate] would set color-scheme={}\n".format(value))
        return ok("Would apply the {} theme.".format(mode))

    result = run_cmd(["gsettings", "set", "org.gnome.desktop.interface",
                      "color-scheme", value], mutate=True, log=log)
    if not result.ok:
        return fail("Could not set color-scheme: {}".format(result.detail()))

    theme = _pick_theme(mode)
    if theme and theme != _current_gtk_theme():
        theme_result = run_cmd(["gsettings", "set", "org.gnome.desktop.interface",
                               "gtk-theme", theme], mutate=True, log=log)
        if not theme_result.ok:
            return fail("Color scheme changed, but gtk-theme failed: {}".format(theme_result.detail()))
    elif log and not theme:
        log.append("[theme] no installed GTK theme matches '{}'; kept current gtk-theme\n".format(mode))
    return ok("Applied the {} theme.".format(mode))


# ---------------------------------------------------------------------------
# Text scaling (macOS-style "larger text" accessibility setting)
# ---------------------------------------------------------------------------
SCALING_SCHEMA = "org.gnome.desktop.interface"
SCALING_KEY = "text-scaling-factor"
SCALING_MIN, SCALING_MAX = 0.8, 2.0


def get_text_scaling() -> float:
    """Current GNOME text scaling factor; 1.0 when it cannot be read."""
    if not has_command("gsettings"):
        return 1.0
    result = run_cmd(["gsettings", "get", SCALING_SCHEMA, SCALING_KEY], quiet=True)
    if not result.ok:
        return 1.0
    try:
        factor = float(result.out.strip().strip("'\""))
    except ValueError:
        return 1.0
    if SCALING_MIN <= factor <= SCALING_MAX:
        return factor
    return 1.0


def set_text_scaling(factor: float, log=None) -> Outcome:
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        return fail("Invalid text scaling factor.")
    if not SCALING_MIN <= factor <= SCALING_MAX:
        return fail("Text scaling must be between {} and {}.".format(SCALING_MIN, SCALING_MAX))
    if not has_command("gsettings"):
        return fail("gsettings is not available; cannot change text scaling.")
    value = "{:.2f}".format(factor)
    if is_simulate():
        if log:
            log.append("[simulate] would set {} to {}\n".format(SCALING_KEY, value))
        return ok("Would set text scaling to {}x.".format(value))
    result = run_cmd(["gsettings", "set", SCALING_SCHEMA, SCALING_KEY, value],
                     mutate=True, log=log)
    if not result.ok:
        return fail("Could not set text scaling: {}".format(result.detail()))
    return ok("Text scaling set to {}x.".format(value))


# ---------------------------------------------------------------------------
# Icon packs
# ---------------------------------------------------------------------------
def install_icon_pack(tar_path: str, log=None) -> Outcome:
    if not os.path.isfile(tar_path):
        return fail("Archive not found: {}".format(tar_path))
    if is_simulate():
        if log:
            log.append("[simulate] would install icon pack {}\n".format(tar_path))
        return ok("Would install icon pack from {}.".format(os.path.basename(tar_path)))

    dest_root = os.path.expanduser("~/.icons")
    tmp_dir = tempfile.mkdtemp(prefix="zoptim-icons-")
    try:
        try:
            tar = tarfile.open(tar_path, "r:*")
        except (tarfile.TarError, OSError) as exc:
            return fail("Not a readable tar archive: {}".format(exc))
        with tar:
            members, rejected = utils.safe_tar_members(tar)
            if rejected:
                if log:
                    log.append("[icons] refused {} unsafe archive entries\n".format(len(rejected)))
                return fail("Archive contains unsafe entries (path traversal, links or devices): {}".format(
                    ", ".join(rejected[:5])))
            if not members:
                return fail("Archive is empty.")
            try:
                tar.extractall(path=tmp_dir, members=members, filter="data")
            except TypeError:  # Python < 3.12
                tar.extractall(path=tmp_dir, members=members)

        theme_dirs = set()
        for root, _dirs, files in os.walk(tmp_dir):
            if "index.theme" in files:
                rel = os.path.relpath(root, tmp_dir)
                if rel != ".":
                    theme_dirs.add(rel.split(os.sep)[0])
        if not theme_dirs:
            return fail("No icon theme found (expected a folder containing index.theme).")
        theme = sorted(theme_dirs)[0]
        source = os.path.join(tmp_dir, theme)
        os.makedirs(dest_root, exist_ok=True)
        target = os.path.join(dest_root, theme)
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.copytree(source, target)
    except (OSError, tarfile.TarError, shutil.Error) as exc:
        return fail("Could not install icon pack: {}".format(exc))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if has_command("gsettings"):
        result = run_cmd(["gsettings", "set", "org.gnome.desktop.interface",
                          "icon-theme", theme], mutate=True, log=log)
        if not result.ok:
            return fail("Installed theme {!r}, but could not activate it: {}".format(
                theme, result.detail()))
    elif log:
        log.append("[icons] gsettings missing; theme installed but not activated\n")
    return ok("Installed and activated icon theme {}.".format(theme))


# ---------------------------------------------------------------------------
# Rounded corners
# ---------------------------------------------------------------------------
def are_rounded_corners_enabled() -> bool:
    try:
        with open(CSS_PATH, "r", encoding="utf-8", errors="ignore") as handle:
            return START_GUARD in handle.read()
    except OSError:
        return False


def set_rounded_corners(enable: bool, log=None) -> Outcome:
    if is_simulate():
        if log:
            log.append("[simulate] would {} rounded-corner CSS\n".format("enable" if enable else "disable"))
        return ok("Would {} rounded corners.".format("enable" if enable else "disable"))
    try:
        content = ""
        if os.path.exists(CSS_PATH):
            with open(CSS_PATH, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
        start = content.find(START_GUARD)
        if start != -1:
            end = content.find(END_GUARD, start)
            if end != -1:
                content = content[:start] + content[end + len(END_GUARD):]
            else:
                content = content[:start]
        if enable:
            if content and not content.endswith("\n"):
                content += "\n"
            content += START_GUARD + CSS_RULE + END_GUARD
        os.makedirs(CSS_DIR, exist_ok=True)
        tmp = CSS_PATH + ".zoptim.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, CSS_PATH)
    except OSError as exc:
        return fail("Could not update gtk.css: {}".format(exc))
    if log:
        log.append("[css] rounded corners {}\n".format("enabled" if enable else "disabled"))
    return ok("Rounded corners {}.".format("enabled" if enable else "disabled"))
