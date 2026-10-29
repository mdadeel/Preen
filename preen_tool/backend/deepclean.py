"""Deep clean: find reclaimable disk space and clean it safely.

Every item shows its size *before* anything is deleted. Mutating commands go
through ``run_cmd(mutate=True)`` so Simulate mode gates them; file deletions
check :func:`utils.is_simulate` explicitly because they never spawn a command.
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Dict, List, Optional

from . import kernels, utils

# The directories a clean action may touch, keyed by scan item. Nothing else
# is ever deleted, new cleanables must be added here explicitly.
USER_CLEAN_PATHS: Dict[str, str] = {
    "thumbnails": os.path.expanduser("~/.cache/thumbnails"),
    "pip_cache": os.path.expanduser("~/.cache/pip"),
    "trash": os.path.expanduser("~/.local/share/Trash/files"),
}

# Human-facing copy for the user-level cleanables, kept next to the paths so
# the scan list and the clean list can never disagree.
USER_CLEAN_INFO: Dict[str, Dict[str, str]] = {
    "thumbnails": {
        "label": "Thumbnail cache",
        "detail": "Image and file previews; they are regenerated automatically.",
    },
    "pip_cache": {
        "label": "Python package cache (pip)",
        "detail": "Downloaded wheels and build artefacts kept by pip.",
    },
    "trash": {
        "label": "Empty trash",
        "detail": "Files moved to the wastebasket.",
    },
}

_JOURNAL_RE = re.compile(
    r"take\s+up\s+([0-9]+(?:\.[0-9]+)?)\s*([BKMGT])", re.IGNORECASE)
_UNITS = {"B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}


def format_size(num_bytes: Optional[float]) -> str:
    """Human-readable size, or ``Unavailable`` for a failed measurement."""
    if num_bytes is None:
        return "Unavailable"
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return "{:.0f} B".format(size)
            return "{:.1f} {}".format(size, unit)
        size /= 1024.0
    return "{:.1f} TB".format(size)


def du_size(path: str) -> Optional[int]:
    """Measure a directory; missing paths are empty, unreadable ones unknown.

    A symlink used as the cleanable root is not followed, matching the
    deletion safety check in :func:`clean_user_paths`.
    """
    try:
        os.lstat(path)
    except FileNotFoundError:
        return 0
    except OSError:
        return None
    if os.path.islink(path):
        return None
    if not os.path.isdir(path):
        return 0
    total = 0
    errors: List[OSError] = []
    try:
        for dirpath, _dirnames, filenames in os.walk(path, onerror=errors.append):
            for name in filenames:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError as exc:
                    errors.append(exc)
    except OSError:
        return None
    return None if errors else total


def parse_journal_usage(text: str) -> int:
    """Parse ``journalctl --disk-usage`` output into bytes (0 if unparsable)."""
    match = _JOURNAL_RE.search(text or "")
    if not match:
        return 0
    return int(float(match.group(1)) * _UNITS[match.group(2).upper()])


def _apt_cache_size() -> Optional[int]:
    return du_size("/var/cache/apt/archives")


def _journal_size() -> Optional[int]:
    if not utils.has_command("journalctl"):
        return None
    result = utils.run_cmd(["journalctl", "--disk-usage"], quiet=True)
    if not result.ok or not _JOURNAL_RE.search(result.out or ""):
        return None
    return parse_journal_usage(result.out)


def scan_cleanable() -> List[dict]:
    """Return cleanables, with ``None`` for sizes that could not be measured."""
    journal_size = _journal_size()
    items = [
        {"key": "apt_cache",
         "label": "APT package cache",
         "detail": "/var/cache/apt/archives. Downloaded .deb files kept after install",
         "size": _apt_cache_size(), "root": True},
        {"key": "journal",
         "label": "System journal logs",
         "detail": "Archived logs only; vacuuming keeps at least 100 MB. Estimate may be lower.",
         # journalctl --disk-usage includes active files which cannot be
         # vacuumed. The amount above the retention limit is an upper bound,
         # not a promise that this much space will actually be recovered.
         "size": max(0, journal_size - 100 * 1024 ** 2) if journal_size is not None else None,
         "root": True},
        {"key": "old_kernels",
         "label": "Old kernel packages",
         "detail": "Kernel versions older than the running one and one spare. "
                   "Never removes the running kernel.",
         "size": kernels.reclaimable_bytes(), "root": True},
    ]
    items.extend(
        {
            "key": key,
            "label": info["label"],
            "detail": USER_CLEAN_PATHS[key] + ". " + info["detail"],
            "size": du_size(USER_CLEAN_PATHS[key]),
            "root": False,
        }
        for key, info in USER_CLEAN_INFO.items()
    )
    items.sort(key=lambda item: item["size"] if item["size"] is not None else -1, reverse=True)
    return items


# ---------------------------------------------------------------------------
# Cleaning actions (mutating, gated by Simulate mode)
# ---------------------------------------------------------------------------
def clean_user_paths(keys: List[str], log=None) -> utils.Outcome:
    """Delete the *contents* of the selected user-level cleanable dirs."""
    paths = []
    for key in keys:
        path = USER_CLEAN_PATHS.get(key)
        if path is None:
            return utils.fail("Unknown cleanable item: {}".format(key))
        paths.append((key, path))

    if utils.is_simulate():
        for key, path in paths:
            if log:
                log.append("[simulate] would clean: {} ({})\n".format(key, path))
        return utils.ok("Simulated: would clean {} item(s).".format(len(paths)))

    errors: List[str] = []
    for key, path in paths:
        try:
            if os.path.islink(path):
                errors.append("{}: cleanable directory is a symbolic link".format(path))
                continue
            if not os.path.isdir(path):
                continue
            for name in os.listdir(path):
                target = os.path.join(path, name)
                try:
                    if os.path.isdir(target) and not os.path.islink(target):
                        shutil.rmtree(target)
                    else:
                        os.remove(target)
                    # Freedesktop Trash keeps a sidecar for each item. Remove
                    # it only after the matching payload was deleted, and do
                    # not follow an unexpected symlinked info directory.
                    if key == "trash" and os.path.basename(path) == "files":
                        info_dir = os.path.join(os.path.dirname(path), "info")
                        if os.path.islink(info_dir):
                            errors.append("{}: trash info directory is a symbolic link".format(info_dir))
                        elif os.path.isdir(info_dir):
                            sidecar = os.path.join(info_dir, name + ".trashinfo")
                            if os.path.lexists(sidecar):
                                try:
                                    os.unlink(sidecar)
                                except OSError as exc:
                                    errors.append("{}: {}".format(sidecar, exc))
                except OSError as exc:
                    errors.append("{}: {}".format(target, exc))
        except OSError as exc:
            errors.append("{}: {}".format(path, exc))
    if errors:
        return utils.fail("Cleaned with {} error(s)".format(len(errors)), *errors[:6])
    return utils.ok("Cleaned {} item(s).".format(len(paths)))


def clean_apt_cache(log=None) -> utils.Outcome:
    report = utils.Report(log)
    report.run(["apt-get", "clean"], use_pkexec=True, mutate=True)
    return report.finish("APT package cache cleaned.", "Could not clean the APT cache")


def vacuum_journal(log=None) -> utils.Outcome:
    report = utils.Report(log)
    report.run(["journalctl", "--vacuum-size=100M"], use_pkexec=True, mutate=True)
    return report.finish("System journal vacuumed to 100 MB.",
                         "Could not vacuum the system journal")


#: Keys understood by :func:`clean_user_paths`, shared with the GUI so both
#: sides agree on which items are file-level (no pkexec) cleans.
USER_KEYS = tuple(USER_CLEAN_PATHS)


def build_clean_actions(selected: List[dict]) -> List[tuple]:
    """Turn selected scan items into ``run_actions`` steps.

    Root items become one pkexec step each; all user-level items are grouped
    into a single ``clean_user_paths`` step.
    """
    actions: List[tuple] = []
    user_keys: List[str] = []
    for item in selected:
        if item.get("root"):
            if item["key"] == "apt_cache":
                actions.append(("APT cache", clean_apt_cache, ()))
            elif item["key"] == "journal":
                actions.append(("System journal", vacuum_journal, ()))
            elif item["key"] == "old_kernels":
                actions.append(("Old kernels", kernels.remove_old_kernels, ()))
        else:
            user_keys.append(item["key"])
    if user_keys:
        actions.append(("User caches & trash", clean_user_paths, (user_keys,)))
    return actions


def total_size(items: List[dict]) -> int:
    """Sum known sizes; callers must separately disclose unknown entries."""
    return sum(int(item.get("size") or 0) for item in items)
