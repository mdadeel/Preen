import os
import tarfile
import time
from .utils import run_cmd

CONFIG_DIR = os.path.expanduser("~/.config")


def export_configs(dest_tar: str, log=None):
    mode = "w:gz" if dest_tar.endswith(".tar.gz") or dest_tar.endswith(".tgz") else "w:xz"
    if log: log.append(f"[backup] export {CONFIG_DIR} -> {dest_tar}\n")
    with tarfile.open(dest_tar, mode) as tar:
        tar.add(CONFIG_DIR, arcname="config")


def import_configs(src_tar: str, log=None):
    if log: log.append(f"[backup] import {src_tar} -> {CONFIG_DIR}\n")
    with tarfile.open(src_tar, "r:*") as tar:
        def is_within_directory(directory, target):
            abs_directory = os.path.abspath(directory)
            abs_target = os.path.abspath(target)
            prefix = os.path.commonprefix([abs_directory, abs_target])
            return prefix == abs_directory
        for member in tar.getmembers():
            target = os.path.join(CONFIG_DIR, os.path.relpath(member.name, "config"))
            if not is_within_directory(CONFIG_DIR, target):
                continue
        tar.extractall(path=os.path.dirname(CONFIG_DIR))


def timeshift_snapshot(comment: str = None, log=None):
    comment = comment or f"Zorin Optimizer {time.strftime('%Y-%m-%d %H:%M')}"
    cmd = ["pkexec", "timeshift", "--create", "--comments", comment, "--tags", "D"]
    if log: log.append(f"[timeshift] {' '.join(cmd)}\n")
    run_cmd(cmd, mutate=True)


def open_timeshift_gui(log=None):
    # Open GUI; does not mutate system state
    run_cmd(["timeshift-gtk"])