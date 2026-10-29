"""UFW firewall status and toggle for the Optimize page.

One command per read, one polkit-gated command per change. Absent tooling
reports ``None`` so the GUI can grey the row out instead of guessing.
"""
from __future__ import annotations

import re
from typing import Optional

from . import utils

_STATUS_RE = re.compile(r"Status:\s*(\S+)")


def ufw_available() -> bool:
    return utils.has_command("ufw")


def ufw_enabled() -> Optional[bool]:
    """True/False when readable, None when ufw is missing or unreadable."""
    if not ufw_available():
        return None
    result = utils.run_cmd(["ufw", "status"], quiet=True)
    if not result.ok:
        return None
    match = _STATUS_RE.search(result.out or "")
    if not match:
        return None
    return match.group(1).lower() == "active"


def set_ufw(enabled: bool, log=None) -> utils.Outcome:
    report = utils.Report(log)
    report.run(["ufw", "--force", "enable" if enabled else "disable"],
               use_pkexec=True, mutate=True)
    return report.finish(
        "Firewall {}.".format("enabled" if enabled else "disabled"),
        "Could not change the firewall")
