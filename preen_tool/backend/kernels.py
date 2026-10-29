"""Installed-kernel inventory for the old-kernel cleanup item.

Groups the image/modules/headers packages dpkg knows about by version,
protects the running kernel plus one spare, and reports what can be purged.
Pure parsing lives here; deepclean.py only calls into it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import utils

# Meta packages (linux-image-generic, linux-modules-extra-*.unsigned …) never
# match: the version part must start with a digit.
_KERNEL_PACKAGE_RE = re.compile(
    r"^(linux-image|linux-modules|linux-modules-extra|linux-headers)-(\d\S*)$")


def parse_installed_kernels(lines) -> Dict[str, List[str]]:
    """Map kernel version -> installed package names for that version."""
    groups: Dict[str, List[str]] = {}
    for line in lines or []:
        name = str(line).strip()
        match = _KERNEL_PACKAGE_RE.match(name)
        if not match:
            continue
        groups.setdefault(match.group(2), []).append(name)
    return groups


def version_sort_key(version: str):
    """Numeric ordering for `6.11.0-19-generic` style versions."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def select_removable(groups: Dict[str, List[str]], running: str,
                     keep: int = 1) -> List[str]:
    """Packages safe to purge: keep the running version and `keep` spares.

    The running kernel is never removable even when dpkg lists it under an
    unexpected version spelling.
    """
    removable: List[str] = []
    kept = 0
    for version in sorted(groups, key=version_sort_key, reverse=True):
        if version == running:
            continue
        kept += 1
        if kept <= keep:
            continue
        removable.extend(sorted(groups[version]))
    return removable


def installed_kernel_packages() -> Optional[List[str]]:
    result = utils.run_cmd(
        ["dpkg-query", "-W", "-f=${Package}\\n"], quiet=True)
    if not result.ok:
        return None
    return result.out.splitlines()


def running_release() -> str:
    result = utils.run_cmd(["uname", "-r"], quiet=True)
    return result.out.strip() if result.ok else ""


def removable_kernel_packages() -> Optional[List[str]]:
    lines = installed_kernel_packages()
    if lines is None:
        return None
    return select_removable(parse_installed_kernels(lines), running_release())


def reclaimable_bytes() -> Optional[int]:
    """Installed-Size total of the removable packages, or None on any failure."""
    packages = removable_kernel_packages()
    if packages is None:
        return None
    if not packages:
        return 0
    result = utils.run_cmd(
        ["dpkg-query", "-W", "-f=${Installed-Size}\\n"] + packages, quiet=True)
    if not result.ok:
        return None
    total = 0
    for line in result.out.splitlines():
        try:
            total += int(line.strip()) * 1024
        except ValueError:
            return None
    return total


def remove_old_kernels(log=None) -> utils.Outcome:
    """Purge the removable kernel packages with one polkit prompt."""
    packages = removable_kernel_packages()
    if packages is None:
        return utils.fail("Could not list the installed kernels.")
    if not packages:
        return utils.ok("No old kernels to remove.")
    report = utils.Report(log)
    report.run(["apt-get", "purge", "-y"] + packages,
               use_pkexec=True, mutate=True, timeout=utils.DEFAULT_TIMEOUT)
    return report.finish(
        "Removed {} old kernel package(s).".format(len(packages)),
        "Could not remove the old kernels")
