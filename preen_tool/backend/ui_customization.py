"""Preen-only appearance and explicitly desktop-wide customization.

System text scaling, icon pack activation and GTK corner CSS affect other apps;
Preen's light/dark preference never changes GNOME appearance settings.
"""
from __future__ import annotations

import math
import os
import shutil
import tarfile
import tempfile
from typing import Optional

from . import settings, utils
from .utils import Outcome, fail, has_command, is_simulate, ok, run_cmd

CSS_DIR = os.path.expanduser("~/.config/gtk-3.0")
CSS_PATH = os.path.join(CSS_DIR, "gtk.css")
START_GUARD = "/* BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
END_GUARD = "/* END ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
CSS_RULE = "window, dialog, .background { border-radius: 10px; }\n"


def _current_gtk_theme() -> str:
    if not has_command("gsettings"):
        return ""
    result = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"], quiet=True)
    return result.out.strip().strip("'\"") if result.ok else ""


def get_theme_mode() -> Optional[str]:
    """Read the GNOME preference, falling back to the GTK 3 theme on older GNOME."""
    if not has_command("gsettings"):
        return None
    result = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], quiet=True)
    value = result.out.strip().strip("'\"").lower() if result.ok else ""
    if value == "prefer-dark":
        return "dark"
    if value == "prefer-light":
        return "light"
    current = _current_gtk_theme()
    if current:
        return "dark" if current.lower().endswith("dark") else "light"
    return "light" if value == "default" else None


def apply_theme_mode(mode: str, log=None) -> Outcome:
    """Save Preen's appearance only; never write GNOME theme settings."""
    mode = mode.lower() if isinstance(mode, str) else ""
    if mode not in settings.VALID_APPEARANCE:
        return fail("Unknown Preen appearance {!r}.".format(mode))
    if is_simulate():
        if log:
            log.append("[simulate] would set Preen appearance to {} (desktop unchanged)\n".format(mode))
        return ok("Simulation complete. No changes were made.")
    if not settings.set_value("appearance_mode", mode):
        return fail("Could not save Preen appearance; check permissions on ~/.config/preen.")
    if log:
        log.append("[appearance] Preen appearance set to {}; desktop unchanged\n".format(mode))
    return ok("Preen appearance set to {}. Desktop theme unchanged.".format(mode))


# ---------------------------------------------------------------------------
# Text scaling (macOS-style "larger text" accessibility setting)
# ---------------------------------------------------------------------------
SCALING_SCHEMA = "org.gnome.desktop.interface"
SCALING_KEY = "text-scaling-factor"
SCALING_MIN, SCALING_MAX = 0.8, 2.0


def get_text_scaling() -> Optional[float]:
    """Return the actual factor, or None if the setting cannot be read."""
    if not has_command("gsettings"):
        return None
    result = run_cmd(["gsettings", "get", SCALING_SCHEMA, SCALING_KEY], quiet=True)
    if not result.ok:
        return None
    try:
        factor = float(result.out.strip().strip("'\""))
    except ValueError:
        return None
    return factor if math.isfinite(factor) and factor > 0 else None


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

        theme_dirs = sorted(root for root, _dirs, files in os.walk(tmp_dir) if "index.theme" in files)
        if not theme_dirs:
            return fail("No icon theme found (expected a folder containing index.theme).")
        source = theme_dirs[0]
        if source == tmp_dir:
            theme = os.path.basename(tar_path)
            for extension in (".tar.xz", ".tar.gz", ".tar.bz2", ".tgz", ".tar"):
                if theme.lower().endswith(extension):
                    theme = theme[:-len(extension)]
                    break
            if not theme or theme in (".", ".."):
                return fail("Could not determine an icon theme name from the archive.")
        else:
            theme = os.path.basename(source)
        if theme.startswith(".preen-"):
            return fail("The icon theme name is reserved by Preen.")
        os.makedirs(dest_root, exist_ok=True)
        target = os.path.join(dest_root, theme)
        stage = tempfile.mkdtemp(prefix=".preen-icons-", dir=dest_root)
        previous = None
        try:
            shutil.copytree(source, stage, dirs_exist_ok=True)
            if os.path.lexists(target):
                backup_dir = os.path.join(dest_root, ".preen-backups")
                if os.path.islink(backup_dir):
                    raise OSError("Icon backup directory is a symbolic link")
                os.makedirs(backup_dir, mode=0o700, exist_ok=True)
                # mkdtemp reserves a unique name; remove the empty placeholder
                # so the previous theme (even a symlink) can be renamed there.
                previous = tempfile.mkdtemp(prefix=theme + "-", dir=backup_dir)
                os.rmdir(previous)
                os.rename(target, previous)
            os.rename(stage, target)
            stage = None
        except (OSError, shutil.Error) as exc:
            if previous and not os.path.lexists(target):
                try:
                    os.rename(previous, target)
                    previous = None
                except OSError as restore_error:
                    raise OSError("{}; original theme remains at {} ({})".format(
                        exc, previous, restore_error)) from exc
            raise
        finally:
            if stage:
                shutil.rmtree(stage, ignore_errors=True)
        if previous and log:
            log.append("[icons] previous theme kept at {}\n".format(previous))
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
        return ok("Installed and activated icon theme {}.".format(theme))
    if log:
        log.append("[icons] gsettings missing; theme installed but not activated\n")
    return ok("Installed icon theme {}, but could not activate it without gsettings.".format(theme))


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
            if end == -1:
                return fail("Rounded-corner CSS marker is incomplete; gtk.css was left unchanged.")
            content = content[:start] + content[end + len(END_GUARD):]
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
