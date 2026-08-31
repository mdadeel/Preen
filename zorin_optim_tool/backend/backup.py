import os
import tarfile
import time
from .utils import run_cmd

CONFIG_DIR = os.path.expanduser("~/.config")


def export_configs(dest_tar: str, log=None):
    mode = "w:gz" if dest_tar.endswith(".tar.gz") or dest_tar.endswith(".tgz") else "w:xz"
    if log: log.append(f"[backup] export {CONFIG_DIR} -> {dest_tar}\n")
    with tarfile.open(dest_tar, mode) as tar:
        tar.add(CONFIG_DIR, arcname=".config")


def import_configs(src_tar: str, log=None):
    if log: log.append(f"[backup] import {src_tar} -> {CONFIG_DIR}\n")
    with tarfile.open(src_tar, "r:*") as tar:
        safe_members = []
        for member in tar.getmembers():
            rel = member.name
            if rel.startswith("config/"):
                rel = rel[7:]
            elif rel.startswith(".config/"):
                rel = rel[8:]
            elif rel in ("config", ".config"):
                continue
            
            # Resolve target path and ensure it remains inside CONFIG_DIR
            target_path = os.path.abspath(os.path.join(CONFIG_DIR, rel))
            if os.path.commonpath([os.path.abspath(CONFIG_DIR), target_path]) == os.path.abspath(CONFIG_DIR):
                member.name = rel
                safe_members.append(member)
            else:
                if log: log.append(f"[backup] [warning] skipped unsafe path: {member.name}\n")
        
        tar.extractall(path=CONFIG_DIR, members=safe_members)


def timeshift_snapshot(comment: str = None, log=None):
    comment = comment or f"Zorin Optimizer {time.strftime('%Y-%m-%d %H:%M')}"
    cmd = ["pkexec", "timeshift", "--create", "--comments", comment, "--tags", "D"]
    if log: log.append(f"[timeshift] {' '.join(cmd)}\n")
    run_cmd(cmd, mutate=True)


def open_timeshift_gui(log=None):
    # Open GUI asynchronously without blocking the background thread
    import subprocess
    from .utils import has_command
    if not has_command("timeshift-gtk"):
        if log: log.append("[timeshift] timeshift-gtk not found in PATH\n")
        return
    if log: log.append("[timeshift] launching timeshift-gtk...\n")
    try:
        subprocess.Popen(["timeshift-gtk"])
    except Exception as e:
        if log: log.append(f"[timeshift] error launching GUI: {e}\n")