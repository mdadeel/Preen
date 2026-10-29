"""Scheduled automatic maintenance via a systemd timer.

Mirrors the root-level Deep Clean tasks (apt cache, autoremove, journal
vacuum, unused Flatpak runtimes) as ``preen-maintenance.timer`` so the machine
stays tidy without the user remembering to open Preen — the Storage Sense
experience Windows users expect. One polkit-gated script installs or removes
the units; reads are plain file reads plus ``systemctl is-enabled``.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Optional

from . import utils
from .utils import fail, ok, run_cmd

SERVICE_PATH = "/etc/systemd/system/preen-maintenance.service"
TIMER_PATH = "/etc/systemd/system/preen-maintenance.timer"
SCRIPT_PATH = "/usr/lib/preen/maintenance"
UNIT_NAME = "preen-maintenance.timer"

# systemd OnCalendar values. RandomizedDelaySec and Persistent keep runs from
# stampeding at boot and let a missed run catch up at the next opportunity.
CALENDARS = {
    "daily": "*-*-* 12:00:00",
    "weekly": "Sun *-*-* 12:00:00",
    "monthly": "*-*-01 12:00:00",
}
DEFAULT_FREQUENCY = "weekly"

_SERVICE_UNIT = """\
[Unit]
Description=Preen automatic maintenance (root-level cleanup tasks)

[Service]
Type=oneshot
ExecStart={script}
"""

_TIMER_UNIT = """\
[Unit]
Description=Run Preen automatic maintenance

[Timer]
OnCalendar={calendar}
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
"""

_MAINTENANCE_SCRIPT = """\
#!/bin/sh
# Installed by Preen. Mirrors the root-level Deep Clean tasks.
apt-get clean
apt-get autoremove -y
journalctl --vacuum-size=100M
command -v flatpak >/dev/null 2>&1 && flatpak uninstall --unused -y --noninteractive
"""

_CALENDAR_RE = re.compile(r"^OnCalendar=(.+)$", re.MULTILINE)


def _read_unit(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _timer_frequency(calendar: str) -> str:
    calendar = (calendar or "").strip()
    for frequency, value in CALENDARS.items():
        if calendar == value:
            return frequency
    return "custom"


def get_schedule() -> Optional[dict]:
    """Current schedule state, or None when systemd units cannot be read."""
    timer_text = _read_unit(TIMER_PATH)
    if not timer_text and not os.path.lexists(TIMER_PATH):
        return {"installed": False, "enabled": False, "frequency": "", "calendar": ""}
    match = _CALENDAR_RE.search(timer_text)
    calendar = match.group(1).strip() if match else ""
    result = run_cmd(["systemctl", "is-enabled", UNIT_NAME], quiet=True)
    enabled = result.ok and (result.out or "").strip() == "enabled"
    return {
        "installed": bool(timer_text) or os.path.lexists(TIMER_PATH),
        "enabled": enabled,
        "frequency": _timer_frequency(calendar),
        "calendar": calendar,
    }


def _unit_script(frequency: str) -> str:
    """One idempotent pkexec script that installs units and starts the timer."""
    calendar = CALENDARS[frequency]
    q_service, q_timer, q_script = (shlex.quote(SERVICE_PATH), shlex.quote(TIMER_PATH),
                                    shlex.quote(SCRIPT_PATH))
    parts = [
        "umask 022",
        "mkdir -p /etc/systemd/system /usr/lib/preen",
        "printf '%s' {svc} > {p}".format(svc=shlex.quote(
            _SERVICE_UNIT.format(script=SCRIPT_PATH)), p=q_service),
        "printf '%s' {tmr} > {p}".format(tmr=shlex.quote(
            _TIMER_UNIT.format(calendar=calendar)), p=q_timer),
        "printf '%s' {sh} > {p}".format(sh=shlex.quote(_MAINTENANCE_SCRIPT), p=q_script),
        "chmod 755 " + q_script,
        "systemctl daemon-reload",
        "systemctl enable --now " + shlex.quote(UNIT_NAME),
    ]
    return " && ".join(parts)


def _removal_script() -> str:
    return " && ".join([
        "systemctl disable --now " + shlex.quote(UNIT_NAME) + " 2>/dev/null || true",
        "rm -f {service} {timer} {script}".format(
            service=shlex.quote(SERVICE_PATH), timer=shlex.quote(TIMER_PATH),
            script=shlex.quote(SCRIPT_PATH)),
        "systemctl daemon-reload",
    ])


def set_schedule(enabled: bool, frequency: str, log=None) -> Outcome:
    """Install or remove the maintenance timer (Simulate mode previews it)."""
    frequency = (frequency or DEFAULT_FREQUENCY).lower()
    if enabled and frequency not in CALENDARS:
        return fail("Unknown maintenance frequency: {!r}".format(frequency))
    if not enabled:
        result = run_cmd(["bash", "-c", _removal_script()],
                         use_pkexec=True, mutate=True, log=log)
        if not result.ok and not result.simulated:
            return fail("Could not remove the maintenance schedule: {}".format(result.detail()))
        return ok("Would disable automatic maintenance." if utils.is_simulate()
                  else "Automatic maintenance disabled.")
    result = run_cmd(["bash", "-c", _unit_script(frequency)],
                     use_pkexec=True, mutate=True, log=log)
    if not result.ok and not result.simulated:
        return fail("Could not enable the maintenance schedule: {}".format(result.detail()))
    if utils.is_simulate():
        return ok("Would schedule {} automatic maintenance.".format(frequency))
    return ok("Automatic maintenance scheduled {} ({}).".format(frequency, CALENDARS[frequency]))
