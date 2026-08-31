import os
import tarfile
from typing import Optional

from .utils import run_cmd


def run_cleanup(log=None):
    if log: log.append("[cleanup] apt-get autoremove -y && apt-get autoclean -y\n")
    cmd = ["pkexec", "bash", "-c", "apt-get autoremove -y && apt-get autoclean -y"]
    run_cmd(cmd, mutate=True)
    if log: log.append("[cleanup] flatpak uninstall --unused -y\n")
    run_cmd(["flatpak", "uninstall", "--unused", "-y"], mutate=True)  # user scope


def set_animations(enabled: bool, log=None):
    state = "true" if enabled else "false"
    if log: log.append(f"[gsettings] org.gnome.desktop.interface enable-animations {state}\n")
    run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "enable-animations", state])


AUTOSTART_DIRS = [
    os.path.expanduser("~/.config/autostart"),
    "/etc/xdg/autostart",
]


def list_startup_apps():
    from .utils import read_desktop_entry
    items = []
    seen = set()
    for d in AUTOSTART_DIRS:
        try:
            for name in os.listdir(d):
                if not name.endswith(".desktop"): continue
                path = os.path.join(d, name)
                if path in seen: continue
                seen.add(path)
                title, hidden = read_desktop_entry(path)
                items.append({"name": title, "hidden": hidden, "path": path})
        except Exception:
            continue
    return items


def set_startup_app(path: str, enabled: bool, log=None) -> bool:
    # Ensure a user override exists, then set Hidden=false/true
    user_dir = os.path.expanduser("~/.config/autostart")
    os.makedirs(user_dir, exist_ok=True)
    base = os.path.basename(path)
    user_path = os.path.join(user_dir, base)
    if not os.path.exists(user_path):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as src, open(user_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())
        except Exception:
            return False
    from .utils import set_autostart_hidden
    ok = set_autostart_hidden(user_path, hidden=not enabled)
    if log: log.append(f"[autostart] {'enable' if enabled else 'disable'} {base}: {'ok' if ok else 'fail'}\n")
    return ok


def are_animations_enabled() -> bool:
    code, out, _ = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"])
    return code == 0 and "true" in out.lower()
