"""Timeshift integration and ~/.config export/import."""
from __future__ import annotations

import os
import re
import subprocess
import tarfile
import time
from typing import Optional

_SNAPSHOT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$")

from . import utils
from .utils import Outcome, fail, has_command, is_simulate, ok, run_cmd

CONFIG_DIR = os.path.expanduser("~/.config")
SKIP_DIR_NAMES = {"Cache", "cache", "CachedData", "GPUCache", "ShaderCache", "Crash Reports"}


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------
def export_configs(dest_tar: str, log=None) -> Outcome:
    dest_tar = os.path.abspath(os.path.expanduser(dest_tar))
    if not os.path.isdir(CONFIG_DIR):
        return fail("Nothing to export: {} does not exist.".format(CONFIG_DIR))
    if is_simulate():
        if log:
            log.append("[simulate] would export {} to {}\n".format(CONFIG_DIR, dest_tar))
        return ok("Would export config to {}.".format(dest_tar))

    mode = "w:gz" if dest_tar.endswith((".tar.gz", ".tgz")) else "w:xz"
    parent = os.path.dirname(dest_tar) or "."
    if not os.path.isdir(parent):
        return fail("Destination folder does not exist: {}".format(parent))

    tmp = dest_tar + ".zoptim.tmp"

    excluded = {os.path.abspath(dest_tar), os.path.abspath(tmp)}

    def _filter(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        parts = info.name.replace("\\", "/").split("/")
        base = parts[-1]
        if base in SKIP_DIR_NAMES or any(p in SKIP_DIR_NAMES for p in parts):
            return None
        # arcname is ".config/...", so the real source path is relative to
        # the PARENT of CONFIG_DIR. Never include the archive being written.
        real_path = os.path.abspath(os.path.join(os.path.dirname(CONFIG_DIR), info.name))
        if real_path in excluded or base.endswith(".zoptim.tmp"):
            return None
        # Only regular files and directories: import refuses links (see
        # safe_tar_members), so exporting them would create archives that the
        # tool itself cannot restore.
        if not (info.isfile() or info.isdir()):
            return None  # sockets, fifos, devices and symlinks
        return info

    try:
        with tarfile.open(tmp, mode) as tar:
            tar.add(CONFIG_DIR, arcname=".config", filter=_filter, recursive=True)
        os.replace(tmp, dest_tar)
    except (OSError, tarfile.TarError) as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return fail("Export failed: {}".format(exc))
    if log:
        log.append("[backup] exported {} -> {}\n".format(CONFIG_DIR, dest_tar))
    return ok("Config exported to {}.".format(dest_tar))


def import_configs(src_tar: str, log=None, dry_safety_check: bool = True) -> Outcome:
    """Restore a config archive inside ~/.config and nowhere else."""
    src_tar = os.path.abspath(os.path.expanduser(src_tar))
    if not os.path.isfile(src_tar):
        return fail("Archive not found: {}".format(src_tar))
    if is_simulate():
        if log:
            log.append("[simulate] would import {} into {}\n".format(src_tar, CONFIG_DIR))
        return ok("Would import config from {}.".format(os.path.basename(src_tar)))
    try:
        tar = tarfile.open(src_tar, "r:*")
    except (OSError, tarfile.TarError) as exc:
        return fail("Not a readable tar archive: {}".format(exc))

    with tar:
        members, rejected = utils.safe_tar_members(tar, strip_prefixes=(".config/", "config/"))
        if rejected and log:
            log.append("[backup] refused {} unsafe entries: {}\n".format(
                len(rejected), ", ".join(rejected[:5])))
        if not members:
            return fail("Archive has no safe files to restore.")
        if dry_safety_check and rejected:
            return fail("Refusing to import: archive contains unsafe entries (path traversal, links or devices).")
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            try:
                tar.extractall(path=CONFIG_DIR, members=members, filter="data")
            except TypeError:  # Python < 3.12
                tar.extractall(path=CONFIG_DIR, members=members)
        except (OSError, tarfile.TarError) as exc:
            return fail("Import failed: {}".format(exc))

    if log:
        log.append("[backup] imported {} file(s) into {}\n".format(len(members), CONFIG_DIR))
    return ok("Imported {} item(s) into {}.".format(len(members), CONFIG_DIR))


def inspect_archive(src_tar: str):
    """Return (safe_count, unsafe_names) without writing anything."""
    try:
        with tarfile.open(src_tar, "r:*") as tar:
            members, rejected = utils.safe_tar_members(tar, strip_prefixes=(".config/", "config/"))
            return len(members), rejected
    except (OSError, tarfile.TarError):
        return 0, ["cannot read archive"]


# ---------------------------------------------------------------------------
# Timeshift
# ---------------------------------------------------------------------------
def parse_snapshot_list(text: str):
    """Parse ``timeshift --list`` rows into plain dicts.

    Rows look like ``0  2024-01-15_10-00-00  D  daily snapshot  2024-01-15 10:00:01``.
    The date always occupies the last two tokens; the description is whatever
    sits between the tags and the date and may be empty.
    """
    snapshots = []
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        num, name, tags = fields[0], fields[1], fields[2]
        tail = fields[3:]
        description, date = "", ""
        # The date always occupies the final two tokens (date then time),
        # so peel it off from the right and keep every word of the
        # description in the middle.
        if len(tail) >= 2 and _SNAPSHOT_DATE_RE.match(" ".join(tail[-2:])):
            date = " ".join(tail[-2:])
            description = " ".join(tail[:-2])
        else:
            description = " ".join(tail)
        snapshots.append({
            "num": num,
            "name": name,
            "tags": tags,
            "description": description,
            "date": date,
        })
    return snapshots


def list_snapshots(log=None):
    """Read-only Timeshift snapshot list; empty when Timeshift is absent."""
    if not has_command("timeshift"):
        return []
    result = run_cmd(["timeshift", "--list"], log=log, timeout=utils.DEFAULT_TIMEOUT)
    if not result.ok:
        return []
    return parse_snapshot_list(result.out)

def timeshift_snapshot(comment: str = None, log=None) -> Outcome:
    if not has_command("timeshift"):
        return fail("Timeshift is not installed. Install it first (sudo apt install timeshift).")
    comment = comment or "Preen {}".format(time.strftime("%Y-%m-%d %H:%M"))
    result = run_cmd(["timeshift", "--create", "--comments", comment, "--tags", "D"],
                     use_pkexec=True, mutate=True, log=log, timeout=utils.DEFAULT_TIMEOUT)
    if not result.ok and not result.simulated:
        return fail("Timeshift snapshot failed: {}".format(result.detail()))
    return ok("Timeshift snapshot requested." if not is_simulate() else "Would create a Timeshift snapshot.")


def open_timeshift_gui(log=None) -> Outcome:
    if is_simulate():
        if log:
            log.append("[simulate] would launch Timeshift GUI\n")
        return ok("Would launch Timeshift.")
    executable = next((name for name in ("timeshift-gtk", "timeshift-launcher")
                       if has_command(name)), None)
    if not executable:
        return fail("Timeshift GUI is not installed (timeshift-gtk / timeshift-launcher).")
    try:
        # Deliberately non-blocking: do not wait for the GUI window to close.
        subprocess.Popen([executable], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return fail("Could not launch Timeshift: {}".format(exc))
    if log:
        log.append("[timeshift] launched {}\n".format(executable))
    return ok("Launched Timeshift.")
