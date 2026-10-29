"""AppImage management: scan downloads, install with desktop integration,
update and uninstall.

Everything happens at user scope — installing someone else's AppImage never
needs root and never touches ``/usr``. The rules mirror the other backend
modules:

* No shell. Paths stay argv elements or plain ``open()`` calls.
* Every mutating entry point honours Simulate mode and returns an Outcome.
* Writes use the tmp + ``os.replace`` idiom so an interrupted install cannot
  leave a half-copied AppImage or a truncated menu entry behind.

The file never executes a downloaded AppImage unless its bytes carry the
type-2 AppImage magic (ELF + ``AI\\x02`` at offset 8); ``--appimage-extract``
is handled by that embedded runtime and never runs the bundled application.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from fnmatch import fnmatch
from typing import Dict, List, Optional, Tuple

from . import utils

APPS_DIR_MAGIC = b"AI\x02"  # type-2 AppImage magic, found at offset 8 of an ELF

ENTRY_PREFIX = "preen-appimage-"
ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9._-]+\.desktop$")
HANDLER_ENTRY_ID = "io.github.mdadeel.Preen.appimage.desktop"
APPIMAGE_MIME_TYPES = ("application/vnd.appimage", "application/x-iso9660-appimage")
FM_SCRIPT_INSTALL = "Install with Preen"
FM_SCRIPT_RUN = "Run with Preen"


# ---------------------------------------------------------------------------
# Locations (resolved at call time so tests can point HOME at a temp dir)
# ---------------------------------------------------------------------------
def data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")


def appimages_dir() -> str:
    """Where Preen copies AppImages it installs."""
    return os.path.join(data_home(), "appimages")


def applications_dir() -> str:
    return os.path.join(data_home(), "applications")


def icons_dir() -> str:
    return os.path.join(data_home(), "icons", "hicolor", "256x256", "apps")


def downloads_dir() -> str:
    """The XDG Downloads directory without importing GLib.

    Parses ``~/.config/user-dirs.dirs`` first (what every desktop tool does),
    falling back to ``~/Downloads``.
    """
    home = os.path.expanduser("~")
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    path = os.path.join(config_home, "user-dirs.dirs")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != "XDG_DOWNLOAD_DIR":
                    continue
                value = value.strip().strip('"')
                expanded = value.replace("$HOME", home).replace("~", home)
                if expanded.startswith("/"):
                    return expanded
    except OSError:
        pass
    return os.path.join(home, "Downloads")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _is_type2_appimage(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    return head[:4] == b"\x7fELF" and head[8:11] == APPS_DIR_MAGIC


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "app"


def _exec_value(path: str) -> str:
    """Quote a path for a desktop Exec key, only when needed.

    Same rule as packaging/install_appimage.sh: paths made of safe characters
    stay bare; anything else is double-quoted with \\ " ` $ escaped.
    """
    if not re.search(r"[^A-Za-z0-9/._-]", path):
        return path
    escaped = (path.replace("\\", "\\\\").replace('"', '\\"')
               .replace("`", "\\`").replace("$", "\\$"))
    return '"' + escaped + '"'


def _exec_target(exec_value: str) -> str:
    """First argv element of a desktop Exec value, unquoted."""
    try:
        parts = shlex.split(exec_value or "")
    except ValueError:
        parts = (exec_value or "").split()
    return parts[0] if parts else ""


def _version_from_filename(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    match = re.search(r"(\d+(?:\.\d+)+)", stem)
    return match.group(1) if match else ""


def _human_size(size: int) -> str:
    if size >= 1024 ** 3:
        return "{:.1f} GB".format(size / 1024 ** 3)
    return "{:.1f} MB".format(size / 1024 ** 2)


def _extract(pattern: str, appimage: str, tmpdir: str) -> List[str]:
    """Extract files matching *pattern* from *appimage* into *tmpdir*.

    Returns the extracted paths (possibly empty). Fails soft: a type-1
    AppImage, a non-executable file or a foreign binary simply extracts
    nothing.
    """
    try:
        proc = subprocess.run(
            [appimage, "--appimage-extract", pattern],
            cwd=tmpdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    root = os.path.join(tmpdir, "squashfs-root")
    if not os.path.isdir(root):
        return []
    hits: List[str] = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), root)
            if _glob_match(pattern, rel):
                hits.append(os.path.join(base, name))
    return sorted(hits)


def _glob_match(pattern: str, rel: str) -> bool:
    """fnmatch against both the basename and the relative path."""
    return fnmatch(os.path.basename(rel), pattern) or fnmatch(rel, pattern)


def _embedded_entry(appimage: str, tmpdir: str) -> Tuple[Optional[Dict[str, object]], List[str]]:
    """Return (desktop-entry info, extracted paths) for *appimage*."""
    hits = _extract("*.desktop", appimage, tmpdir)
    for candidate in hits:
        info = utils.parse_desktop_file(candidate)
        if str(info["type"]).lower() == "application" and not info["no_display"] and not info["hidden"]:
            return info, hits
    return None, hits


def _materialize(hit: str, appimage: str, tmpdir: str) -> Optional[str]:
    """Follow extracted symlinks by re-extracting their targets.

    AppImages link their root icon (``recordly.png``) to the real file under
    ``usr/share/icons/...`` — extraction materialises only the dangling link,
    so each hop must be extracted by its squashfs-relative path.
    """
    current = hit
    seen = set()
    for _hop in range(4):
        if os.path.isfile(current) and not os.path.islink(current):
            return current
        if not os.path.islink(current):
            return None
        rel = os.path.normpath(os.readlink(current)).lstrip("/")
        if rel.startswith("..") or rel in seen:
            return None
        seen.add(rel)
        extracted = _extract(rel, appimage, tmpdir)
        current = extracted[0] if extracted else None
        if current is None:
            return None
    return None


def _extract_icon(appimage: str, icon_key: str, tmpdir: str,
                  app_name: str = "") -> Optional[str]:
    """Best-effort icon extraction; returns an existing real file or None.

    Tries the Icon key, then ``.DirIcon``, then a root-level image named
    after the icon key or the app (some AppImages say ``Icon=recordly`` while
    shipping ``recordly.png`` under another spelling).
    """
    if icon_key:
        for ext in (".png", ".svg"):
            for hit in _extract(icon_key + ext, appimage, tmpdir):
                resolved = _materialize(hit, appimage, tmpdir)
                if resolved:
                    return resolved
    for hit in _extract(".DirIcon", appimage, tmpdir):
        resolved = _materialize(hit, appimage, tmpdir)
        if resolved:
            return resolved
    root = os.path.join(tmpdir, "squashfs-root")
    candidates = []
    for hit in _extract("*.png", appimage, tmpdir) + _extract("*.svg", appimage, tmpdir):
        if os.path.dirname(hit) != root:
            continue
        resolved = _materialize(hit, appimage, tmpdir)
        if resolved:
            candidates.append(resolved)
    by_stem = {}
    for hit in candidates:
        by_stem.setdefault(os.path.splitext(os.path.basename(hit))[0].lower(), hit)
    for key in (icon_key, app_name):
        if key and key.lower() in by_stem:
            return by_stem[key.lower()]
    if len(candidates) == 1:
        return candidates[0]
    return None


# ---------------------------------------------------------------------------
# Scanners
# ---------------------------------------------------------------------------
def list_downloads(warnings=None, log=None) -> List[Dict]:
    """AppImage files sitting in the Downloads directory, with install state."""
    installed_slugs = set()
    for row in list_installed():
        installed_slugs.add(_slug(str(row["name"])))
        entry_id = str(row["id"])
        if entry_id.startswith(ENTRY_PREFIX):
            installed_slugs.add(entry_id[len(ENTRY_PREFIX):-len(".desktop")])

    directory = downloads_dir()
    items: List[Dict] = []
    for path in sorted(glob.glob(os.path.join(directory, "*.AppImage"))) + \
            sorted(glob.glob(os.path.join(directory, "*.appimage"))):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        app_name, version, icon_key = stem, _version_from_filename(path), ""
        if _is_type2_appimage(path):
            tmpdir = tempfile.mkdtemp(prefix="preen-scan-")
            try:
                info, _hits = _embedded_entry(path, tmpdir)
                if info:
                    app_name = str(info["name"]) or stem
                    icon_key = str(info["icon"])
                    embedded_version = str(info["x_appimage_version"] or "")
                    version = embedded_version or version
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        items.append({
            "kind": "download",
            "id": path,
            "path": path,
            "name": app_name,
            "version": version,
            "size": _human_size(size),
            "installed": _slug(app_name) in installed_slugs,
            "protected": False,
        })
    items.sort(key=lambda x: str(x["name"]).lower())
    return items


def list_installed(warnings=None, log=None) -> List[Dict]:
    """User-level menu entries whose Exec points at an AppImage file.

    Deliberately scans the entry, not a fixed directory: AppImageLauncher and
    hand-made entries are covered too. Only Preen's own installs (under
    ``appimages_dir()``) get ``managed=True``, which gates binary deletion.
    """
    managed_dir = os.path.realpath(appimages_dir())
    items: List[Dict] = []
    for entry in sorted(glob.glob(os.path.join(applications_dir(), "*.desktop"))):
        info = utils.parse_desktop_file(entry)
        if str(info["type"]).lower() != "application" or info["no_display"] or info["hidden"]:
            continue
        target = _exec_target(str(info["exec"]))
        if not target.lower().endswith(".appimage") or not os.path.exists(target):
            continue
        entry_id = os.path.basename(entry)
        items.append({
            "kind": "installed",
            "id": entry_id,
            "path": target,
            "name": str(info["name"]),
            "version": str(info["x_appimage_version"] or ""),
            "managed": os.path.realpath(target).startswith(managed_dir + os.sep),
            "protected": False,
        })
    items.sort(key=lambda x: str(x["name"]).lower())
    return items


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def _refresh_caches(log=None) -> None:
    if utils.has_command("update-desktop-database"):
        utils.run_cmd(["update-desktop-database", applications_dir()],
                      quiet=True, log=log)
    if utils.has_command("gtk-update-icon-cache"):
        utils.run_cmd(["gtk-update-icon-cache", "-f", "-t",
                       os.path.dirname(os.path.dirname(icons_dir()))],
                      quiet=True, log=log)


def install_appimage(path: str, log=None) -> utils.Outcome:
    """Install *path* with a menu entry and icon, replacing any previous copy.

    Re-running it over an installed app is the update path: the AppImage and
    the menu entry are replaced in place, the versionless target name keeps
    the entry stable across versions. The downloaded original stays where it
    is (a copy, never a move).
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return utils.fail("Not a file: {}".format(path))
    name_hint = os.path.basename(path)
    if utils.is_simulate():
        return utils.ok("Would install {} with a menu entry and icon.".format(name_hint))

    # The AppImage must be executable for the embedded runtime to extract and
    # for the menu entry to launch it at all.
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as exc:
        return utils.fail("Could not make {} executable: {}".format(name_hint, exc))

    app_name = os.path.splitext(name_hint)[0]
    icon_key = ""
    comment = "AppImage application"
    version = _version_from_filename(path)
    tmpdir = tempfile.mkdtemp(prefix="preen-install-")
    try:
        if _is_type2_appimage(path):
            info, _hits = _embedded_entry(path, tmpdir)
            if info:
                app_name = str(info["name"]) or app_name
                icon_key = str(info["icon"])
                if info.get("comment"):
                    comment = str(info["comment"])
                version = str(info["x_appimage_version"] or "") or version
        slug = _slug(app_name)
        target = os.path.join(appimages_dir(), slug + ".AppImage")
        entry_path = os.path.join(applications_dir(), ENTRY_PREFIX + slug + ".desktop")

        try:
            os.makedirs(appimages_dir(), exist_ok=True)
            os.makedirs(applications_dir(), exist_ok=True)

            tmp = target + ".zoptim.tmp"
            shutil.copyfile(path, tmp)
            os.chmod(tmp, 0o755)
            os.replace(tmp, target)

            icon_value = "application-x-executable"
            icon_src = (_extract_icon(path, icon_key, tmpdir, app_name)
                        if icon_key else None)
            if icon_src and os.path.isfile(icon_src):
                ext = os.path.splitext(icon_src)[1] or ".png"
                icon_path = os.path.join(icons_dir(), slug + ext)
                os.makedirs(icons_dir(), exist_ok=True)
                icon_tmp = icon_path + ".zoptim.tmp"
                shutil.copyfile(icon_src, icon_tmp)
                os.replace(icon_tmp, icon_path)
                icon_value = slug

            entry = "[Desktop Entry]\n"
            entry += "Type=Application\n"
            entry += "Name={}\n".format(app_name)
            entry += "Comment={}\n".format(comment)
            entry += "Exec={}\n".format(_exec_value(target))
            entry += "Icon={}\n".format(icon_value)
            entry += "Terminal=false\n"
            entry += "Categories=Utility;\n"
            entry += "StartupNotify=true\n"
            if version:
                entry += "X-AppImage-Version={}\n".format(version)
            entry += "X-Preen-Source={}\n".format(_exec_value(path))

            entry_tmp = entry_path + ".zoptim.tmp"
            with open(entry_tmp, "w", encoding="utf-8") as handle:
                handle.write(entry)
            os.replace(entry_tmp, entry_path)
        except OSError as exc:
            return utils.fail("Could not install {}: {}".format(name_hint, exc))

        _refresh_caches(log=log)
        details = ["AppImage: {}".format(target), "Menu entry: {}".format(entry_path)]
        if version:
            details.append("Version: {}".format(version))
        return utils.ok("Installed {} — find it in the app menu.".format(app_name), *details)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def uninstall_appimage(entry_id: str, log=None) -> utils.Outcome:
    """Remove a user-level AppImage menu entry.

    The AppImage binary itself is deleted only when it lives inside Preen's
    ``appimages_dir()`` — anything else (AppImageLauncher layouts, hand-made
    entries) loses only the entry and its Preen-written icon.
    """
    if not ENTRY_ID_RE.match(entry_id or "") or "/" in entry_id or "\\" in entry_id:
        return utils.fail("Invalid menu entry id: {!r}".format(entry_id))
    entry_path = os.path.join(applications_dir(), entry_id)
    if not os.path.isfile(entry_path):
        return utils.fail("No such AppImage menu entry: {}".format(entry_id))
    info = utils.parse_desktop_file(entry_path)
    app_name = str(info["name"]) or entry_id
    if utils.is_simulate():
        return utils.ok("Would remove the menu entry for {}.".format(app_name))

    removed: List[str] = []
    try:
        target = _exec_target(str(info["exec"]))
        if target and os.path.realpath(target).startswith(
                os.path.realpath(appimages_dir()) + os.sep) and os.path.isfile(target):
            os.remove(target)
            removed.append("AppImage: {}".format(target))

        # Icons are shared naming space; only clean up the ones Preen wrote.
        if entry_id.startswith(ENTRY_PREFIX):
            slug = entry_id[len(ENTRY_PREFIX):-len(".desktop")]
            for ext in (".png", ".svg", ".xpm"):
                icon_path = os.path.join(icons_dir(), slug + ext)
                if os.path.isfile(icon_path):
                    os.remove(icon_path)
                    removed.append("Icon: {}".format(icon_path))

        os.remove(entry_path)
        removed.append("Menu entry: {}".format(entry_path))
    except OSError as exc:
        return utils.fail("Could not remove {}: {}".format(app_name, exc))

    _refresh_caches(log=log)
    return utils.ok("Removed {}.".format(app_name), *removed)


def install_appimages(paths: List[str], log=None) -> utils.Outcome:
    """Install several AppImages, reporting a per-file outcome for each."""
    if not paths:
        return utils.fail("No AppImages selected.")
    outcomes = [install_appimage(path, log=log) for path in paths]
    failed = [o for o in outcomes if not o.ok]
    if not failed:
        return utils.ok(
            "Installed {} AppImage(s).".format(len(outcomes)),
            *[o.message for o in outcomes])
    summary = "Installed {} of {} AppImage(s)".format(len(outcomes) - len(failed), len(outcomes))
    if len(failed) == len(outcomes):
        summary = "No AppImage could be installed"
    return utils.fail(summary, *[o.message for o in failed])


def uninstall_appimages(entry_ids: List[str], log=None) -> utils.Outcome:
    """Remove several AppImage installs, reporting a per-entry outcome."""
    if not entry_ids:
        return utils.fail("No AppImage installs selected.")
    outcomes = [uninstall_appimage(entry_id, log=log) for entry_id in entry_ids]
    failed = [o for o in outcomes if not o.ok]
    if not failed:
        return utils.ok("Removed {} AppImage install(s).".format(len(outcomes)),
                        *[o.message for o in outcomes])
    summary = "Removed {} of {} AppImage install(s)".format(len(outcomes) - len(failed), len(outcomes))
    if len(failed) == len(outcomes):
        summary = "No AppImage install could be removed"
    return utils.fail(summary, *[o.message for o in failed])


def install_deb(path: str, log=None) -> utils.Outcome:
    """Install a local .deb with one polkit prompt (used by drag-and-drop)."""
    from . import apps as apps_backend  # late import: apps.py is heavy

    path = os.path.abspath(path)
    if not os.path.isfile(path) or not path.lower().endswith(".deb"):
        return utils.fail("Not a .deb package: {}".format(path))
    report = utils.Report(log)
    report.run(["apt-get", "install", "-y", path],
               use_pkexec=True, mutate=True, timeout=utils.DEFAULT_TIMEOUT)
    outcome = report.finish(
        "Installed {}.".format(os.path.basename(path)),
        "Could not install {}".format(os.path.basename(path)))
    apps_backend.invalidate_state()
    return outcome


# ---------------------------------------------------------------------------
# File-manager integration ("Run / Install with Preen" on right-click)
# ---------------------------------------------------------------------------
def app_name_for_file(path: str) -> str:
    """Best-effort application name for an AppImage file, without installing."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if not _is_type2_appimage(path):
        return stem
    tmpdir = tempfile.mkdtemp(prefix="preen-name-")
    try:
        info, _hits = _embedded_entry(path, tmpdir)
        if info and info.get("name"):
            return str(info["name"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return stem


def find_installed_for_file(path: str) -> Optional[Dict]:
    """The installed AppImage row matching *path*, or None (slug match)."""
    slug = _slug(app_name_for_file(path))
    for row in list_installed():
        if _slug(str(row["name"])) == slug or \
                str(row["id"]) == ENTRY_PREFIX + slug + ".desktop":
            return row
    return None


def run_appimage(path: str, log=None) -> utils.Outcome:
    """Launch an AppImage detached; never blocks and never opens a window."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return utils.fail("Not a file: {}".format(path))
    if utils.is_simulate():
        return utils.ok("Would run {}.".format(os.path.basename(path)))
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        subprocess.Popen([path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return utils.fail("Could not launch {}: {}".format(os.path.basename(path), exc))
    return utils.ok("Launched {}.".format(os.path.basename(path)))


def nautilus_scripts_dir() -> str:
    return os.path.join(data_home(), "nautilus", "scripts")


def _fm_script_body(command: str, flag: str) -> str:
    # $APPIMAGE is exported by the AppImage runtime when Preen itself runs as
    # an AppImage; otherwise the installed `preen` command is used.
    return ("#!/usr/bin/env bash\n"
            "# Generated by Preen - right-click integration. Safe to delete.\n"
            'printf \'%s\' "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | '
            "while IFS= read -r f; do\n"
            '    [ -n "$f" ] && {} {} "$f" >/dev/null 2>&1 &\n'
            "done\n".format(command, flag))


def _handler_base_command() -> str:
    return _exec_value(os.environ.get("APPIMAGE") or "preen")


def filemanager_scripts_installed() -> bool:
    directory = nautilus_scripts_dir()
    return all(os.path.isfile(os.path.join(directory, name))
               for name in (FM_SCRIPT_INSTALL, FM_SCRIPT_RUN))


def set_filemanager_scripts(enabled: bool, log=None) -> utils.Outcome:
    """Add or remove the right-click 'Install/Run with Preen' entries."""
    if utils.is_simulate():
        return utils.ok("Would {} the right-click menu entries."
                        .format("add" if enabled else "remove"))
    directory = nautilus_scripts_dir()
    try:
        if not enabled:
            removed = 0
            for name in (FM_SCRIPT_INSTALL, FM_SCRIPT_RUN):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            return utils.ok("Removed the right-click menu entries."
                            if removed else
                            "The right-click menu entries were not installed.")
        os.makedirs(directory, exist_ok=True)
        for name, flag in ((FM_SCRIPT_INSTALL, "--appimage-handler"),
                           (FM_SCRIPT_RUN, "--appimage-run")):
            path = os.path.join(directory, name)
            tmp = path + ".zoptim.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(_fm_script_body(_handler_base_command(), flag))
            os.chmod(tmp, 0o755)
            os.replace(tmp, path)
    except OSError as exc:
        return utils.fail("Could not update the right-click menu entries: {}".format(exc))
    return utils.ok("Added 'Install with Preen' and 'Run with Preen' to the "
                    "file manager right-click menu.")


def default_appimage_handler() -> str:
    result = utils.run_cmd(["xdg-mime", "query", "default", APPIMAGE_MIME_TYPES[0]],
                           quiet=True)
    return result.out.strip() if result.ok else ""


def set_default_appimage_handler(log=None) -> utils.Outcome:
    """Make Preen's handler the default for .AppImage double-clicks.

    One xdg-mime call per mimetype: some xdg-utils versions write only the
    last type when several are passed at once. The config directory must
    exist first — xdg-mime silently no-ops (exit 0, nothing written) when it
    cannot touch mimeapps.list.
    """
    report = utils.Report(log)
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    try:
        os.makedirs(config_home, exist_ok=True)
    except OSError:
        pass
    for mime_type in APPIMAGE_MIME_TYPES:
        report.run(["xdg-mime", "default", HANDLER_ENTRY_ID, mime_type],
                   mutate=True)
    return report.finish("Preen now opens .AppImage files by default.",
                         "Could not set the default AppImage handler")
