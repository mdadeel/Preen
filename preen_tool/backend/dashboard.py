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


def _load_average_text() -> str:
    try:
        load = os.getloadavg()
    except (OSError, AttributeError):
        return ""
    return "{:.2f}, {:.2f}, {:.2f}".format(load[0], load[1], load[2])


def _proc_memory_values():
    """Read Linux memory counters; absent/unreadable counters stay unknown."""
    values = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return values


def _fallback_swap():
    values = _proc_memory_values()
    if "SwapTotal" not in values or "SwapFree" not in values:
        return None, None, None
    total = values["SwapTotal"]
    used = max(0, total - values["SwapFree"])
    return (round(100.0 * used / total, 1) if total else 0.0, used, total)


def _fallback_memory():
    values = _proc_memory_values()
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None, None, None
    used = max(0, total - available)
    return round(100.0 * used / total, 1), used, total


def _fallback_cpu():
    """Sample /proc/stat rather than presenting a fabricated zero percent."""
    def sample():
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            fields = handle.readline().split()
        if not fields or fields[0] != "cpu" or len(fields) < 5:
            raise ValueError("CPU counters unavailable")
        # The first eight fields are non-overlapping (guest is already
        # included in user/nice). iowait counts as idle.
        numbers = [int(value) for value in fields[1:9]]
        idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
        return sum(numbers), idle

    try:
        first_total, first_idle = sample()
        time.sleep(0.12)
        total, idle = sample()
        delta = total - first_total
        if delta <= 0:
            return None
        return round(max(0.0, min(100.0, 100.0 * (1 - (idle - first_idle) / delta))), 1)
    except (OSError, ValueError, IndexError):
        return None


def get_system_info() -> Dict[str, str]:
    # Each counter is independent: a failure in one must not hide the rest or
    # turn a missing reading into a plausible-looking zero.
    cpu = None
    cores = os.cpu_count()
    if psutil is not None:
        try:
            cpu = psutil.cpu_percent(interval=0.2)
            cores = psutil.cpu_count(logical=True) or cores
        except Exception:
            pass
    if cpu is None:
        cpu = _fallback_cpu()

    mem_percent, mem_used, mem_total = _fallback_memory()
    swap_percent, swap_used, swap_total = _fallback_swap()
    disk_percent, disk_used, disk_total = None, None, None
    uptime = None
    if psutil is not None:
        try:
            mem = psutil.virtual_memory()
            mem_percent, mem_used, mem_total = mem.percent, mem.used, mem.total
        except Exception:
            pass
        try:
            swap = psutil.swap_memory()
            swap_percent, swap_used, swap_total = swap.percent, swap.used, swap.total
        except Exception:
            pass
        try:
            disk = psutil.disk_usage("/")
            disk_percent, disk_used, disk_total = disk.percent, disk.used, disk.total
        except Exception:
            pass
        try:
            uptime = time.time() - psutil.boot_time()
        except Exception:
            pass
    if disk_total is None:
        try:
            stat = os.statvfs("/")
            disk_total = stat.f_blocks * stat.f_frsize
            disk_used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
            disk_percent = round(100.0 * disk_used / disk_total, 1) if disk_total else None
        except OSError:
            pass
    if uptime is None:
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                uptime = float(handle.read().split()[0])
        except (OSError, ValueError, IndexError):
            pass

    power = ""
    if has_command("powerprofilesctl"):
        result = run_cmd(["powerprofilesctl", "get"], quiet=True)
        power = result.out.strip() if result.ok else ""

    def percent(value):
        return str(round(value, 1)) if value is not None else "Unavailable"

    def capacity(used, total):
        if used is None or total is None:
            return "Unavailable"
        gib = 1024.0 ** 3
        return "{:.1f} / {:.1f} GiB".format(used / gib, total / gib)

    return {
        "cpu_percent": percent(cpu),
        "cpu_cores": str(cores) if cores else "Unavailable",
        "mem_percent": percent(mem_percent),
        "mem_used": capacity(mem_used, mem_total),
        "disk_percent": percent(disk_percent),
        "disk_used": capacity(disk_used, disk_total),
        "swap_percent": percent(swap_percent),
        "swap_used": capacity(swap_used, swap_total),
        "load_average": _load_average_text(),
        "os": _os_pretty_name(),
        "kernel": platform.uname().release,
        "uptime": _uptime_text(uptime) if uptime is not None else "Unavailable",
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


def feature_warnings() -> List[str]:
    """Plain-language explanations of which features are unavailable.

    The GUI shows these once at startup instead of silently disabling buttons
    and letting the user discover a broken feature by clicking it.
    """
    warnings: List[str] = []
    checks = [
        ("flatpak", "Flatpak is not installed. Flatpak installs and the Flatpak half of Manage Apps are unavailable."),
        ("apt-get", "APT was not found, so package management is unavailable."),
        ("pkexec", "pkexec (polkit) is missing, so APT, swapfile and ZRAM changes cannot be authorised."),
        ("gsettings", "gsettings is unavailable, so theme, icon and animation options will not apply."),
        ("powerprofilesctl", "power-profiles-daemon is missing, so the power profile selector is disabled."),
        ("timeshift", "Timeshift is not installed, so snapshot buttons will report an error."),
    ]
    for command, message in checks:
        if not has_command(command):
            warnings.append(message)
    return warnings
