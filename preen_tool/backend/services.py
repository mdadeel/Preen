"""systemd services management and boot-time analysis.

Read-only listings use plain ``systemctl`` calls; anything that changes a
unit goes through ``run_cmd(mutate=True)`` so Simulate mode gates it, and
polkit authorises it like every other mutating action.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import utils

#: Only well-formed unit names ever reach systemctl, defence in depth on top
#: of never passing user input through a shell.
_UNIT_RE = re.compile(r"^[A-Za-z0-9@._\-\\]+\.service$")
ACTIONS = ("enable", "disable", "start", "stop", "restart")
_PAST_TENSE = {
    "enable": "enabled",
    "disable": "disabled",
    "start": "started",
    "stop": "stopped",
    "restart": "restarted",
}


def valid_unit_name(unit: str) -> bool:
    return bool(_UNIT_RE.match(unit or ""))


def parse_list_units(text: str) -> List[dict]:
    """Parse ``systemctl list-units --type=service --all --no-legend`` output.

    Columns: UNIT LOAD ACTIVE SUB DESCRIPTION (description may contain spaces).
    """
    units: List[dict] = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5 or not parts[0].endswith(".service"):
            continue
        units.append({
            "unit": parts[0],
            "load": parts[1],
            "active": parts[2],
            "sub": parts[3],
            "description": parts[4],
        })
    return units


def parse_unit_files(text: str) -> Dict[str, str]:
    """Parse ``systemctl list-unit-files`` output into unit -> state."""
    states: Dict[str, str] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(".service"):
            states[parts[0]] = parts[1]
    return states


def list_services(log=None) -> Optional[List[dict]]:
    """Merge live units and unit-file states; None means the scan failed."""
    live_result = utils.run_cmd(
        ["systemctl", "list-units", "--type=service", "--all",
         "--no-legend", "--no-pager"], quiet=True)
    if not live_result.ok:
        if log:
            log.append("[warning] Service listing failed (exit {}): {}\n".format(
                live_result.code, live_result.err or live_result.out or "no output"))
        return None
    live = parse_list_units(live_result.out)
    files_result = utils.run_cmd(
        ["systemctl", "list-unit-files", "--type=service",
         "--no-legend", "--no-pager"], quiet=True)
    files = parse_unit_files(files_result.out) if files_result.ok else {}
    if not files_result.ok and log:
        log.append("[warning] Service startup states unavailable (exit {}): {}\n".format(
            files_result.code, files_result.err or files_result.out or "no output"))
    for entry in live:
        entry["unit_state"] = files.get(entry["unit"], "")
    return live


def set_service_state(unit: str, action: str, log=None) -> utils.Outcome:
    """enable/disable/start/stop a system unit via one polkit prompt."""
    if action not in ACTIONS:
        return utils.fail("Unsupported service action: {}".format(action))
    if not valid_unit_name(unit):
        return utils.fail("Not a valid unit name: {}".format(unit))
    report = utils.Report(log)
    report.run(["systemctl", action, unit], use_pkexec=True, mutate=True)
    return report.finish("Service {} {}.".format(unit, _PAST_TENSE[action]),
                         "Could not {} {}".format(action, unit))


def parse_analyze(text: str) -> Dict[str, str]:
    """Parse ``systemd-analyze`` summary output into phase -> seconds."""
    info: Dict[str, str] = {}
    match = re.search(
        r"=\s*([0-9.]+(?:ms|s|min))\s*$", text or "")
    if match:
        info["total"] = match.group(1)
    for phase in ("firmware", "loader", "kernel", "userspace", "initrd"):
        match = re.search(
            r"([0-9.]+(?:ms|s|min))\s*\(\s*" + phase, text or "")
        if match:
            info[phase] = match.group(1)
    return info


def parse_blame(text: str, limit: int = 8) -> List[Tuple[str, str]]:
    """Parse ``systemd-analyze blame`` into (unit, seconds), slowest first."""
    rows: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0][0].isdigit() and parts[1].endswith(".service"):
            rows.append((parts[1].strip(), parts[0].strip()))
        if len(rows) >= limit:
            break
    return rows


def boot_info(log=None) -> Dict[str, object]:
    """Boot summary + slowest units; empty if the data cannot be read."""
    if not utils.has_command("systemd-analyze"):
        if log:
            log.append("[warning] systemd-analyze is not installed.\n")
        return {}
    info: Dict[str, object] = {}
    summary = utils.run_cmd(["systemd-analyze"], quiet=True)
    if summary.ok:
        info.update(parse_analyze(summary.out))
    elif log:
        log.append("[warning] Boot analysis failed (exit {}): {}\n".format(
            summary.code, summary.err or summary.out or "no output"))
    blame = utils.run_cmd(
        ["systemd-analyze", "blame", "--no-pager"], quiet=True)
    if blame.ok:
        info["blame"] = parse_blame(blame.out)
    elif log:
        log.append("[warning] Slow-service analysis failed (exit {}): {}\n".format(
            blame.code, blame.err or blame.out or "no output"))
    return info
