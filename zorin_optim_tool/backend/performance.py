import os
from .utils import run_cmd, has_command


def set_power_profile(profile: str, log=None):
    # Use powerprofilesctl if available
    if has_command("powerprofilesctl"):
        cmd = ["powerprofilesctl", "set", profile]
        if log: log.append(f"[power] {' '.join(cmd)}\n")
        run_cmd(cmd)
    else:
        if log: log.append("[power] powerprofilesctl not available\n")


SWAPFILE = "/swapfile"


def enable_swapfile(size_gb: int = 2, log=None):
    # If swap already active, skip
    code, out, _ = run_cmd(["swapon", "--show"])
    if out.strip():
        if log: log.append("[swap] swap already active\n")
        return
    # Create swapfile using a single pkexec bash command to avoid prompt fatigue
    size_mb = size_gb * 1024
    cmd_str = (
        f"fallocate -l {size_mb}M {SWAPFILE} && "
        f"chmod 600 {SWAPFILE} && "
        f"mkswap {SWAPFILE} && "
        f"swapon {SWAPFILE} && "
        f"(grep -q '{SWAPFILE}' /etc/fstab || echo '{SWAPFILE} none swap sw 0 0' >> /etc/fstab)"
    )
    cmd = ["pkexec", "bash", "-c", cmd_str]
    if log: log.append(f"[swap] { ' '.join(cmd) }\n")
    run_cmd(cmd, mutate=True)


def disable_swapfile(log=None):
    # Turn off swap and remove /swapfile line from fstab using a single pkexec command
    cmd_str = (
        f"swapoff {SWAPFILE} 2>/dev/null || true; "
        f"sed -i.bak '\\|{SWAPFILE}|d' /etc/fstab; "
        f"[ -f {SWAPFILE} ] && rm -f {SWAPFILE} || true"
    )
    cmd = ["pkexec", "bash", "-c", cmd_str]
    if log: log.append(f"[swap] { ' '.join(cmd) }\n")
    run_cmd(cmd, mutate=True)


ZRAM_CFG = "/etc/systemd/zram-generator.conf"


def enable_zram(log=None):
    # Enable via systemd zram-generator if available
    if not os.path.exists("/usr/lib/systemd/system-generators/systemd-zram-generator") and \
       not os.path.exists("/lib/systemd/system-generators/systemd-zram-generator"):
        if log: log.append("[zram] zram-generator not available; skipping\n")
        return
    cfg = """[zram0]
zram-size = ram / 2
"""
    cmd = ["pkexec", "bash", "-lc", f"printf '%s' \"{cfg}\" > {ZRAM_CFG} && systemctl daemon-reload && systemctl start /dev/zram0 || true"]
    if log: log.append(f"[zram] {' '.join(cmd)}\n")
    run_cmd(cmd, mutate=True)


def disable_zram(log=None):
    if not os.path.exists(ZRAM_CFG):
        if log: log.append("[zram] config not present\n")
        return
    cmd_str = f"swapoff /dev/zram0 2>/dev/null || true; rm -f {ZRAM_CFG} && systemctl daemon-reload"
    cmd = ["pkexec", "bash", "-c", cmd_str]
    if log: log.append(f"[zram] { ' '.join(cmd) }\n")
    run_cmd(cmd, mutate=True)


def is_swapfile_active() -> bool:
    code, out, _ = run_cmd(["swapon", "--show"])
    return code == 0 and SWAPFILE in out


def is_zram_active() -> bool:
    code, out, _ = run_cmd(["swapon", "--show"])
    return code == 0 and "zram" in out
