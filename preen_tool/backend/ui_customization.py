"""Light/dark theme, icon packs and rounded-corner CSS.

Everything here used to bypass Simulate mode and write files even during a
"dry run". Icon pack extraction also used a bare ``tar.extractall`` (path
traversal) and guessed the theme name from directory mtimes.
"""
from __future__ import annotations

import math
import os
import re
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
    # GTK 3 bundles these themes as resources, even when /usr/share/themes
    # has no corresponding directories (common on minimal GNOME installs).
    themes: Set[str] = {"Adwaita", "Adwaita-dark"}
    for root in _theme_roots():
        try:
            themes.update(
                name for name in os.listdir(root)
                if os.path.isdir(os.path.join(root, name, "gtk-3.0"))
            )
        except OSError:
            continue
    return themes


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


def _pick_theme(mode: str, current: Optional[str] = None) -> Optional[str]:
    """Prefer the current theme's installed light/dark partner, then Adwaita."""
    installed = _installed_themes()
    current = _current_gtk_theme() if current is None else current
    suffix = re.search(r"(?:[-_]?dark|[-_]?light)$", current, flags=re.IGNORECASE)
    stem = current[:suffix.start()] if suffix else current
    is_dark = current.lower().endswith("dark")
    if mode == "dark":
        candidates = ([current] if is_dark else []) + [
            stem + "-dark", stem + "-Dark", stem + "_dark", stem + "Dark",
            "Adwaita-dark", "Yaru-dark", "ZorinBlue-Dark"]
    else:
        candidates = ([current] if current and not is_dark else []) + [
            stem, stem + "-Light", stem + "-light", stem + "_light", stem + "Light",
            "Adwaita", "Yaru", "ZorinBlue-Light"]
    return next((name for name in candidates if name and name in installed), None)


def apply_theme_mode(mode: str, log=None) -> Outcome:
    mode = (mode or "").lower()
    if mode not in ("light", "dark"):
        return fail("Unknown theme mode {!r}.".format(mode))
    if not has_command("gsettings"):
        return fail("gsettings is not available.")

    schema = "org.gnome.desktop.interface"
    available = run_cmd(["gsettings", "list-keys", schema], quiet=True)
    if not available.ok:
        return fail("Could not inspect GNOME appearance settings: {}".format(available.detail()))
    keys = set(available.out.splitlines())
    has_scheme, has_theme = "color-scheme" in keys, "gtk-theme" in keys
    if not (has_scheme or has_theme):
        return fail("This desktop exposes neither color-scheme nor gtk-theme settings.")

    current = _current_gtk_theme() if has_theme else ""
    if has_theme and not current:
        return fail("Could not read the current GTK theme; no appearance changes were made.")
    theme = _pick_theme(mode, current) if has_theme else None
    if has_theme and not theme:
        return fail("No installed GTK theme matches the {} appearance.".format(mode))

    # On older GNOME, color-scheme does not exist. GTK 3's theme setting is
    # then the sole supported path; modern desktops use both where available.
    if has_scheme:
        value = "prefer-dark" if mode == "dark" else "default"
        result = run_cmd(["gsettings", "set", schema, "color-scheme", value],
                         mutate=True, log=log)
        if not result.ok:
            return fail("Could not set color-scheme: {}".format(result.detail()))
    if theme and theme != current:
        result = run_cmd(["gsettings", "set", schema, "gtk-theme", theme],
                         mutate=True, log=log)
        if not result.ok:
            prefix = "Color scheme changed, but " if has_scheme and not is_simulate() else ""
            return fail("{}gtk-theme failed: {}".format(prefix, result.detail()))
    if is_simulate():
        return ok("Simulation complete. No changes were made.")
    return ok("Applied the {} appearance.".format(mode))


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
