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
    # Create swapfile using pkexec
    size_mb = size_gb * 1024
    cmds = [
        ["pkexec", "bash", "-lc", f"fallocate -l {size_mb}M {SWAPFILE}"],
        ["pkexec", "bash", "-lc", f"chmod 600 {SWAPFILE}"],
        ["pkexec", "bash", "-lc", f"mkswap {SWAPFILE}"],
        ["pkexec", "bash", "-lc", f"swapon {SWAPFILE}"],
        ["pkexec", "bash", "-lc", f"grep -q '{SWAPFILE}' /etc/fstab || echo '{SWAPFILE} none swap sw 0 0' >> /etc/fstab"],
    ]
    for c in cmds:
        if log: log.append(f"[swap] {' '.join(c)}\n")
        run_cmd(c, mutate=True)


def disable_swapfile(log=None):
    # Turn off swap and remove /swapfile line from fstab
    if log: log.append("[swap] swapoff -a\n")
    run_cmd(["pkexec", "swapoff", "-a"], mutate=True)  # may error if none; ignore
    # Remove swapfile and fstab entry
    cmds = [
        ["pkexec", "bash", "-lc", f"sed -i.bak '\\|{SWAPFILE}|d' /etc/fstab"],
        ["pkexec", "bash", "-lc", f"[ -f {SWAPFILE} ] && rm -f {SWAPFILE} || true"],
    ]
    for c in cmds:
        if log: log.append(f"[swap] {' '.join(c)}\n")
        run_cmd(c, mutate=True)


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
    cmds = [
        ["pkexec", "bash", "-lc", "swapoff /dev/zram0 || true"],
        ["pkexec", "bash", "-lc", f"rm -f {ZRAM_CFG} && systemctl daemon-reload"],
    ]
    for c in cmds:
        if log: log.append(f"[zram] {' '.join(c)}\n")
        run_cmd(c, mutate=True)
