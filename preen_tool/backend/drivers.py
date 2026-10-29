"""Graphics/driver discovery and installation via ``ubuntu-drivers``.

Windows hands drivers to users; Zorin hides them in Software & Updates ->
Additional Drivers. This surfaces ``ubuntu-drivers devices`` as rows and
installs the chosen packages through the same polkit-gated apt path the rest
of the backend uses. Reads never escalate; only installs do.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import utils
from .utils import Report, fail, format_cmd, has_command, is_simulate, ok, run_cmd

PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_SECTION_RE = re.compile(r"^==\s*(.+?)\s*==$")
_FIELD_RE = re.compile(r"^([a-z]+):\s*(.*)$")


def parse_devices(text: str) -> List[Dict]:
    """Parse ``ubuntu-drivers devices`` into device rows.

    Sections look like::

        == /sys/devices/pci0000:00/0000:01:00.0 ==
        modalias: pci:v000010DEd00001C82...
        vendor:  NVIDIA Corporation
        model:   GP104 [GeForce GTX 1070]
        driver:  nvidia-driver-535 - distro non-free recommended

    A ``driver:`` line becomes a package entry; ``recommended`` anywhere in
    the tags marks it. Unparseable lines are ignored.
    """
    devices: List[Dict] = []
    current: Optional[Dict] = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        section = _SECTION_RE.match(line)
        if section:
            current = {"modalias": "", "vendor": "", "model": section.group(1),
                       "packages": []}
            devices.append(current)
            continue
        if current is None:
            continue
        field = _FIELD_RE.match(line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip()
        if key == "modalias":
            current["modalias"] = value
        elif key == "vendor":
            current["vendor"] = value
        elif key == "model":
            current["model"] = value
        elif key == "driver" and value:
            parts = [part.strip() for part in value.split(" - ", 1)]
            name = parts[0].split()[0] if parts and parts[0] else ""
            if not PACKAGE_RE.match(name):
                continue
            tags = parts[1] if len(parts) > 1 else ""
            current["packages"].append({
                "name": name,
                "recommended": "recommended" in tags.lower(),
                "note": tags,
            })
    return devices


def _summary(devices: List[Dict]) -> str:
    recommended = sum(1 for device in devices
                      for package in device["packages"] if package["recommended"])
    return "{} driver device(s), {} recommended package(s)".format(len(devices), recommended)


def list_devices(log=None) -> Dict:
    """Run ``ubuntu-drivers devices``; returns {devices, warnings, available}."""
    warnings: List[str] = []
    if not has_command("ubuntu-drivers"):
        return {"devices": [], "warnings": ["ubuntu-drivers is not installed"],
                "available": False}
    result = run_cmd(["ubuntu-drivers", "devices"], quiet=True)
    if not result.ok:
        warnings.append("ubuntu-drivers devices failed (exit {}): {}".format(
            result.code, result.err or result.out or "no output"))
        return {"devices": [], "warnings": warnings, "available": True}
    return {"devices": parse_devices(result.out), "warnings": warnings,
            "available": True}


def install_driver(packages: List[str], log=None) -> utils.Outcome:
    """Install the selected driver packages via polkit-gated apt."""
    names = [str(name).strip() for name in packages or []]
    names = [name for name in names if name]
    if not names:
        return fail("No driver packages selected.")
    bad = [name for name in names if not PACKAGE_RE.match(name)]
    if bad:
        return fail("Refusing to install invalid package name(s): {}".format(", ".join(bad)))
    if is_simulate():
        if log:
            log.append("[simulate] would install: {}\n".format(" ".join(names)))
        return ok("Would install {} driver package(s).".format(len(names)))
    report = Report(log)
    script = "DEBIAN_FRONTEND=noninteractive " + format_cmd(
        ["apt-get", "install", "-y"] + names)
    report.run(["bash", "-c", script], use_pkexec=True, mutate=True)
    return report.finish(
        "Installed {} driver package(s).".format(len(names)),
        "Driver installation finished with errors",
    )


def autoinstall(log=None) -> utils.Outcome:
    """Let ubuntu-drivers pick and install everything it recommends."""
    if not has_command("ubuntu-drivers"):
        return fail("ubuntu-drivers is not installed. Install ubuntu-drivers-common first.")
    if is_simulate():
        if log:
            log.append("[simulate] would run: ubuntu-drivers autoinstall\n")
        return ok("Would let ubuntu-drivers install the recommended drivers.")
    report = Report(log)
    script = "DEBIAN_FRONTEND=noninteractive " + format_cmd(["ubuntu-drivers", "autoinstall"])
    report.run(["bash", "-c", script], use_pkexec=True, mutate=True)
    return report.finish("Recommended drivers installed.",
                         "Automatic driver installation failed")
