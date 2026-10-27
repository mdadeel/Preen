"""System information for the dashboard and the CLI doctor."""
from __future__ import annotations

import os
import platform
import time
from typing import Dict, List

try:  # psutil is a declared dependency, but the app must still start without it
    import psutil
except ImportError:  # pragma: no cover - exercised only on minimal systems
    psutil = None

from .utils import has_command, run_cmd


def _os_pretty_name() -> str:
    values: Dict[str, str] = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            for line in handle:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values.get("PRETTY_NAME") or "{} {}".format(platform.system(), platform.release())


def _uptime_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return "{}d {}h {}m".format(days, hours, minutes)
    if hours:
        return "{}h {}m".format(hours, minutes)
    return "{}m".format(minutes)


def _fallback_memory():
    try:
        values = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", total)
        used = total - available
        return round(100.0 * used / total, 1) if total else 0.0, used, total
    except (OSError, ValueError, IndexError):
        return 0.0, 0, 0


def get_system_info() -> Dict[str, str]:
    if psutil is not None:
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        mem_percent, mem_used, mem_total = mem.percent, mem.used, mem.total
        disk = psutil.disk_usage("/")
        disk_percent, disk_used, disk_total = disk.percent, disk.used, disk.total
        uptime = time.time() - psutil.boot_time()
        cores = psutil.cpu_count(logical=True) or 1
    else:
        cpu, cores = 0.0, 1
        mem_percent, mem_used, mem_total = _fallback_memory()
        disk_percent, disk_used, disk_total = 0.0, 0, 0
        try:
            stat = os.statvfs("/")
            disk_total = stat.f_blocks * stat.f_frsize
            disk_used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
            disk_percent = round(100.0 * disk_used / disk_total, 1) if disk_total else 0.0
        except OSError:
            pass
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                uptime = float(handle.read().split()[0])
        except (OSError, ValueError):
            uptime = 0.0

    power = ""
    if has_command("powerprofilesctl"):
        result = run_cmd(["powerprofilesctl", "get"], quiet=True)
        power = result.out.strip() if result.ok else ""

    gib = 1024.0 ** 3
    return {
        "cpu_percent": str(round(cpu, 1)),
        "cpu_cores": str(cores),
        "mem_percent": str(round(mem_percent, 1)),
        "mem_used": "{:.1f} / {:.1f} GiB".format(mem_used / gib, mem_total / gib),
        "disk_percent": str(round(disk_percent, 1)),
        "disk_used": "{:.1f} / {:.1f} GiB".format(disk_used / gib, disk_total / gib),
        "os": _os_pretty_name(),
        "kernel": platform.uname().release,
        "uptime": _uptime_text(uptime),
        "power_profile": power,
    }


def capabilities() -> List[Dict[str, str]]:
    """Dependency checks used by `--doctor` and shown in the dashboard."""
    checks = [
        ("python3-gi (GTK 3)", "gi", False),
        ("psutil", "psutil", False),
        ("flatpak", "flatpak", True),
        ("APT / dpkg", "apt-get", True),
        ("gsettings", "gsettings", True),
        ("pkexec (polkit)", "pkexec", True),
        ("power-profiles-daemon", "powerprofilesctl", False),
        ("Timeshift", "timeshift", False),
    ]
    result = []
    for label, key, required in checks:
        if key == "gi":
            found = _has_gi()
        elif key == "psutil":
            found = psutil is not None
        else:
            found = has_command(key)
        result.append({
            "name": label,
            "required": required,
            "status": "ok" if found else ("missing" if required else "optional"),
        })
    return result


def _has_gi() -> bool:
    try:
        import gi  # noqa: F401
        return True
    except ImportError:
        return False
