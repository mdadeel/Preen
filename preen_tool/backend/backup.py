"""Timeshift integration and ~/.config export/import."""
from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
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


def _destination_conflicts(members):
    """Detect existing links/non-regular files before changing any config."""
    conflicts = []
    if os.path.islink(CONFIG_DIR):
        return ["configuration directory is a symbolic link"]
    for member in members:
        path = CONFIG_DIR
        parts = member.name.rstrip("/").split("/")
        for index, part in enumerate(parts):
            path = os.path.join(path, part)
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                break
            except OSError as exc:
                conflicts.append("{} ({})".format(member.name, exc))
                break
            needs_dir = index < len(parts) - 1 or member.isdir()
            if stat.S_ISLNK(mode) or (needs_dir and not stat.S_ISDIR(mode)) or (
                    not needs_dir and not stat.S_ISREG(mode)):
                conflicts.append("{} (destination is a link or incompatible file)".format(member.name))
                break
    return conflicts


def _extract_configs(tar, members):
    """Extract via directory descriptors without following destination links.

    This works on Python versions without tarfile's ``filter=`` argument and
    avoids a check-then-extract race through an existing symlink. Each file is
    written to a sibling temporary file and atomically replaces the old file.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(CONFIG_DIR, directory_flags)
    try:
        for member in members:
            parts = member.name.rstrip("/").split("/")
            parent_fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = next_fd
                leaf = parts[-1]
                if member.isdir():
                    try:
                        os.mkdir(leaf, member.mode, dir_fd=parent_fd)
                    except FileExistsError:
                        fd = os.open(leaf, directory_flags, dir_fd=parent_fd)
                        os.close(fd)
                    continue
                try:
                    existing = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    existing = None
                if existing is not None and not stat.S_ISREG(existing.st_mode):
                    raise OSError("Refusing non-regular destination: {}".format(member.name))
                source = tar.extractfile(member)
                if source is None:
                    raise tarfile.ExtractError("Cannot read {}".format(member.name))
                temporary = ".preen-restore-" + secrets.token_hex(12)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             member.mode, dir_fd=parent_fd)
                try:
                    with source, os.fdopen(fd, "wb") as output:
                        shutil.copyfileobj(source, output)
                    os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)


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
        conflicts = _destination_conflicts(members)
        if conflicts:
            return fail("Refusing to import through unsafe or incompatible destination paths.", *conflicts[:5])
        try:
            _extract_configs(tar, members)
        except (OSError, tarfile.TarError) as exc:
            return fail("Import failed; some earlier files may already have been restored: {}".format(exc))

    if log:
        log.append("[backup] imported {} file(s) into {}\n".format(len(members), CONFIG_DIR))
    return ok("Imported {} item(s) into {}.".format(len(members), CONFIG_DIR))


def inspect_archive(src_tar: str):
    """Return (safe_count, unsafe_names) without writing anything."""
    try:
        with tarfile.open(src_tar, "r:*") as tar:
            members, rejected = utils.safe_tar_members(tar, strip_prefixes=(".config/", "config/"))
            rejected.extend(_destination_conflicts(members))
            return len(members), rejected
    except (OSError, tarfile.TarError):
        return 0, ["cannot read archive"]


# ---------------------------------------------------------------------------
# Timeshift
# ---------------------------------------------------------------------------
def parse_snapshot_list(text: str):
    """Parse ``timeshift --list`` rows into plain dicts.

    Rows may contain a ``>`` marker and often have no description or separate
    date column. Some Timeshift versions add a date as the last two tokens.
    """
    snapshots = []
    for line in (text or "").splitlines():
        fields = line.split()
        if not fields or not fields[0].isdigit():
            continue
        num, fields = fields[0], fields[1:]
        if fields and fields[0] == ">":
            fields = fields[1:]
        if len(fields) < 2:
            continue
        name, tags = fields[:2]
        tail = fields[2:]
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


def list_snapshots(privileged=False, log=None):
    """List snapshots, using polkit only for an explicit user refresh.

    Timeshift normally requires root even to list snapshots. Startup probes
    without prompting; an explicit refresh can request authorisation. In
    simulation the privileged command is previewed but never executed.
    """
    if not has_command("timeshift"):
        if log:
            log.append("[warning] Timeshift is not installed; snapshot list unavailable.\n")
        return None
    if is_simulate() and not privileged:
        if log:
            log.append("[simulate] skipped the Timeshift startup probe.\n")
        return None
    if privileged and not is_simulate() and log:
        log.append("[timeshift] Requesting administrator access to list snapshots.\n")
    result = run_cmd(["timeshift", "--list"], use_pkexec=privileged, mutate=privileged,
                     env={"LC_ALL": "C"}, log=log, timeout=120,
                     quiet=not (privileged and is_simulate()))
    if result.simulated:
        return None
    if not result.ok:
        # Timeshift itself exits 1 for a successful query with no snapshots.
        if "No snapshots found" in result.out and not result.err.strip():
            if log:
                log.append("[timeshift] No snapshots found.\n")
            return []
        if log:
            log.append("[warning] Timeshift list unavailable (exit {}). "
                       "Use Refresh List or Open Timeshift for administrator access.\n".format(result.code))
            for label, output in (("stdout", result.out), ("stderr", result.err)):
                if output:
                    log.append("[{}]\n{}{}".format(label, output, "" if output.endswith("\n") else "\n"))
        return None
    return parse_snapshot_list(result.out)

def timeshift_snapshot(comment: str = None, log=None) -> Outcome:
    if not has_command("timeshift"):
        return fail("Timeshift is not installed. Install it first (sudo apt install timeshift).")
    comment = comment or "Preen {}".format(time.strftime("%Y-%m-%d %H:%M"))
    result = run_cmd(["timeshift", "--create", "--comments", comment, "--tags", "O"],
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
