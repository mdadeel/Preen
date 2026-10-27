"""Power profiles, swapfile and ZRAM.

Every destructive path is guarded by a real state check and by Simulate mode.
The old code deleted ``/swapfile`` on *every* optimization run (even when the
user never enabled it) and started a nonexistent ``/dev/zram0`` unit.
"""
from __future__ import annotations

import os
import shlex
from typing import List

from . import utils
from .utils import Outcome, fail, has_command, is_simulate, ok, run_cmd

SWAPFILE = "/swapfile"
FSTAB_ENTRY = SWAPFILE + " none swap sw 0 0"
ZRAM_CFG = "/etc/systemd/zram-generator.conf"
ZRAM_UNIT = "systemd-zram-setup@zram0.service"
POWER_PROFILES = ("balanced", "power-saver", "performance")


# ---------------------------------------------------------------------------
# Read-only state
# ---------------------------------------------------------------------------
def _swap_devices() -> List[str]:
    result = run_cmd(["swapon", "--show"], quiet=True)
    if result.ok:
        lines = result.out.splitlines()
        if lines and lines[0].lstrip().upper().startswith("NAME"):
            lines = lines[1:]
        return [line.split()[0] for line in lines if line.strip()]
    # Fallback for minimal systems where swapon is missing.
    try:
        with open("/proc/swaps", "r", encoding="utf-8") as handle:
            return [line.split()[0] for line in handle.readlines()[1:] if line.strip()]
    except OSError:
        return []


def is_swapfile_active() -> bool:
    return SWAPFILE in _swap_devices()


def is_zram_active() -> bool:
    return any(device.startswith("/dev/zram") for device in _swap_devices())


def is_zram_configured() -> bool:
    return os.path.exists(ZRAM_CFG)


def get_power_profile() -> str:
    if not has_command("powerprofilesctl"):
        return ""
    result = run_cmd(["powerprofilesctl", "get"], quiet=True)
    return result.out.strip() if result.ok else ""


def set_power_profile(profile: str, log=None) -> Outcome:
    if profile not in POWER_PROFILES:
        return fail("Invalid power profile {!r}. Choose one of: {}".format(
            profile, ", ".join(POWER_PROFILES)))
    if not has_command("powerprofilesctl"):
        return fail("powerprofilesctl is not available. Install power-profiles-daemon.")
    if is_simulate():
        if log:
            log.append("[simulate] would set power profile to {}\n".format(profile))
        return ok("Would set power profile to {}.".format(profile))
    result = run_cmd(["powerprofilesctl", "set", profile], mutate=True, log=log)
    if not result.ok:
        return fail("Could not set power profile: {}".format(result.detail()))
    return ok("Power profile set to {}.".format(profile))


# ---------------------------------------------------------------------------
# Swapfile
# ---------------------------------------------------------------------------
def enable_swapfile(size_gb: int = 2, log=None) -> Outcome:
    try:
        size_gb = int(size_gb)
    except (TypeError, ValueError):
        return fail("Invalid swap size.")
    if not 1 <= size_gb <= 64:
        return fail("Swap size must be between 1 and 64 GB.")

    if is_swapfile_active():
        return ok("{} is already active.".format(SWAPFILE))

    size_mb = size_gb * 1024
    script = "\n".join([
        "set -e",
        "if [ ! -e {f} ]; then".format(f=shlex.quote(SWAPFILE)),
        "  fallocate -l {n}G {f} 2>/dev/null || dd if=/dev/zero of={f} bs=1M count={m} status=none".format(
            n=size_gb, f=shlex.quote(SWAPFILE), m=size_mb),
        "fi",
        "chmod 600 " + shlex.quote(SWAPFILE),
        "mkswap " + shlex.quote(SWAPFILE) + " >/dev/null",
        "swapon " + shlex.quote(SWAPFILE),
        "if [ -n \"$(tail -c 1 /etc/fstab)\" ]; then printf '\\n' >> /etc/fstab; fi",
        "grep -qxF {entry} /etc/fstab || printf '%s\\n' {entry} >> /etc/fstab".format(
            entry=shlex.quote(FSTAB_ENTRY)),
    ])
    result = run_cmd(["bash", "-c", script], use_pkexec=True, mutate=True,
                     log=log, timeout=utils.DEFAULT_TIMEOUT)
    if not result.ok and not result.simulated:
        return fail("Could not enable swapfile: {}".format(result.detail()))
    return ok("Enabled a {} GB swapfile.".format(size_gb) if not is_simulate()
              else "Would enable a {} GB swapfile.".format(size_gb))


def disable_swapfile(log=None) -> Outcome:
    # Do NOT touch anything unless this tool's swapfile actually exists.
    # (The old implementation ran `rm -f /swapfile` and rewrote /etc/fstab
    # every single time the user pressed "Run Optimization".)
    if not os.path.exists(SWAPFILE) and not is_swapfile_active():
        return ok("No {} to disable.".format(SWAPFILE))
    if is_simulate():
        if log:
            log.append("[simulate] would disable and remove {}\n".format(SWAPFILE))
        return ok("Would disable and remove the swapfile.")
    sed_expr = r"/^[[:space:]]*\/swapfile[[:space:]]/d"
    script = "\n".join([
        "set -e",
        "if swapon --show=NAME --noheadings 2>/dev/null | grep -qx {f}; then swapoff {f}; fi".format(
            f=shlex.quote(SWAPFILE)),
        "sed -i.zoptim.bak " + shlex.quote(sed_expr) + " /etc/fstab",
        "rm -f " + shlex.quote(SWAPFILE),
    ])
    result = run_cmd(["bash", "-c", script], use_pkexec=True, mutate=True, log=log)
    if not result.ok and not result.simulated:
        return fail("Could not disable swapfile: {}".format(result.detail()))
    return ok("Swapfile disabled and removed.")


# ---------------------------------------------------------------------------
# ZRAM
# ---------------------------------------------------------------------------
def _has_zram_generator() -> bool:
    candidates = [
        "/usr/lib/systemd/system-generators/systemd-zram-generator",
        "/usr/lib/systemd/system-generators/zram-generator",
        "/lib/systemd/system-generators/systemd-zram-generator",
        "/lib/systemd/system-generators/zram-generator",
    ]
    return any(os.path.exists(path) for path in candidates)


def enable_zram(log=None) -> Outcome:
    if not _has_zram_generator():
        return fail("systemd-zram-generator is not installed. Install systemd-zram-generator first.")
    if is_zram_configured() and is_zram_active():
        return ok("ZRAM is already configured and active.")
    config = "[zram0]\nzram-size = ram / 2\ncompression-algorithm = zstd\n"
    script = " && ".join([
        "printf '%s' {cfg} > {path}".format(cfg=shlex.quote(config), path=shlex.quote(ZRAM_CFG)),
        "systemctl daemon-reload",
        "systemctl start " + shlex.quote(ZRAM_UNIT),
    ])
    result = run_cmd(["bash", "-c", script], use_pkexec=True, mutate=True, log=log)
    if not result.ok and not result.simulated:
        return fail("Could not enable ZRAM: {}".format(result.detail()))
    return ok("ZRAM enabled." if not is_simulate() else "Would enable ZRAM.")


def disable_zram(log=None) -> Outcome:
    if not is_zram_configured() and not is_zram_active():
        return ok("ZRAM is not configured.")
    if is_simulate():
        if log:
            log.append("[simulate] would disable ZRAM and remove {}\n".format(ZRAM_CFG))
        return ok("Would disable ZRAM.")
    script = " && ".join([
        "(systemctl stop {unit} 2>/dev/null || true)".format(unit=shlex.quote(ZRAM_UNIT)),
        "rm -f " + shlex.quote(ZRAM_CFG),
        "systemctl daemon-reload",
    ])
    result = run_cmd(["bash", "-c", script], use_pkexec=True, mutate=True, log=log)
    if not result.ok and not result.simulated:
        return fail("Could not disable ZRAM: {}".format(result.detail()))
    return ok("ZRAM disabled.")
