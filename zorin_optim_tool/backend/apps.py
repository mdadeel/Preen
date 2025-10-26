from .utils import run_cmd, has_command, ensure_flathub
from typing import List, Dict, Tuple
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
APPS_JSON = os.path.join(CONFIG_DIR, "apps.json")


def load_apps() -> Dict[str, List[Dict]]:
    try:
        with open(APPS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "Browsers": [
                {"id": "org.mozilla.firefox", "name": "Firefox", "flatpak": "org.mozilla.firefox", "apt": "firefox"},
                {"id": "com.google.Chrome", "name": "Google Chrome", "flatpak": "com.google.Chrome"},
                {"id": "com.brave.Browser", "name": "Brave", "flatpak": "com.brave.Browser"}
            ],
            "Dev Tools": [
                {"id": "code", "name": "VS Code", "flatpak": "com.visualstudio.code"},
                {"id": "git", "name": "Git", "apt": "git"},
                {"id": "node", "name": "Node.js (LTS)", "flatpak": "org.freedesktop.Sdk.Extension.node18"},
                {"id": "python3", "name": "Python3", "apt": "python3"}
            ],
            "Media": [
                {"id": "vlc", "name": "VLC", "flatpak": "org.videolan.VLC", "apt": "vlc"},
                {"id": "gimp", "name": "GIMP", "flatpak": "org.gimp.GIMP", "apt": "gimp"},
                {"id": "obs", "name": "OBS Studio", "flatpak": "com.obsproject.Studio"}
            ],
            "Utilities": [
                {"id": "stacer", "name": "Stacer", "flatpak": "com.github.oguzhaninan.Stacer"},
                {"id": "timeshift", "name": "Timeshift", "apt": "timeshift"}
            ]
        }


def _flatpak_installed(ref: str) -> bool:
    code, out, _ = run_cmd(["flatpak", "list", "--columns=application"])
    return code == 0 and any(line.strip() == ref for line in out.splitlines())


def _apt_installed(pkg: str) -> bool:
    code, out, _ = run_cmd(["dpkg-query", "-W", "-f=${Status}", pkg])
    return code == 0 and "installed" in out


def get_status_map(source: str) -> Dict[str, bool]:
    apps = load_apps()
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    status = {}
    for aid, item in all_items.items():
        if source == "flatpak" and item.get("flatpak"):
            status[aid] = _flatpak_installed(item["flatpak"])
        elif source == "apt" and item.get("apt"):
            status[aid] = _apt_installed(item["apt"])
        else:
            status[aid] = False
    return status


def list_installed_flatpak() -> List[Dict]:
    code, out, _ = run_cmd(["flatpak", "list", "--app", "--columns=application,name"])
    items = []
    if code == 0:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split("\t")]
            if not parts or len(parts[0]) == 0:
                continue
            app_id = parts[0]
            name = parts[1] if len(parts) > 1 else app_id
            items.append({"source": "flatpak", "id": app_id, "name": name})
    return items


def list_installed_apt() -> List[Dict]:
    # List installed packages; this can be large
    code, out, _ = run_cmd(["dpkg-query", "-W", "-f=${Package}\t${Status}\n"])
    items = []
    if code == 0:
        for line in out.splitlines():
            try:
                pkg, status = line.split("\t", 1)
            except ValueError:
                continue
            if "install ok installed" in status:
                items.append({"source": "apt", "id": pkg, "name": pkg})
    return items


def uninstall_installed(entries: List[Dict], log=None):
    for it in entries:
        src = it.get("source")
        ident = it.get("id")
        if src == "flatpak":
            cmd = ["flatpak", "uninstall", "-y", ident]
            if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        elif src == "apt":
            cmd = ["pkexec", "apt-get", "remove", "-y", ident]
            if log: log.append(f"[apt] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)

def update_installed(entries: List[Dict], log=None):
    # Update specific installed entries
    apt_updated_index = False
    for it in entries:
        src = it.get("source")
        ident = it.get("id")
        if src == "flatpak":
            cmd = ["flatpak", "update", "-y", ident]
            if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        elif src == "apt":
            if not apt_updated_index:
                run_cmd(["pkexec", "apt-get", "update"], mutate=True)
                apt_updated_index = True
            cmd = ["pkexec", "apt-get", "install", "--only-upgrade", "-y", ident]
            if log: log.append(f"[apt] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)


def install_apps(app_ids: List[str], source: str, log=None):
    ensure_flathub()
    apps = load_apps()
    # Flatten list
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    for aid in app_ids:
        item = all_items.get(aid)
        if not item:
            continue
        if source == "flatpak" and "flatpak" in item:
            ref = item["flatpak"]
            if _flatpak_installed(ref):
                if log: log.append(f"[install] {item['name']} already installed (Flatpak)\n")
                continue
            cmd = ["flatpak", "install", "-y", "flathub", ref]
            if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        elif source == "apt" and "apt" in item:
            pkg = item["apt"]
            if _apt_installed(pkg):
                if log: log.append(f"[install] {item['name']} already installed (APT)\n")
                continue
            run_cmd(["pkexec", "apt-get", "update"], mutate=True)  # escalate for apt
            cmd = ["pkexec", "apt-get", "install", "-y", pkg]
            if log: log.append(f"[apt] install {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        else:
            if log: log.append(f"[skip] {item.get('name', aid)} unsupported source {source}\n")


def update_all(source: str, log=None):
    if source == "flatpak":
        cmd = ["flatpak", "update", "-y"]
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    else:
        run_cmd(["pkexec", "apt-get", "update"], mutate=True)  # update indices
        cmd = ["pkexec", "apt-get", "upgrade", "-y"]
        if log: log.append(f"[apt] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


def update_apps(app_ids: List[str], source: str, log=None):
    apps = load_apps()
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    if source == "flatpak":
        for aid in app_ids:
            item = all_items.get(aid)
            if not item or not item.get("flatpak"):
                continue
            cmd = ["flatpak", "update", "-y", item["flatpak"]]
            if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
    elif source == "apt":
        run_cmd(["pkexec", "apt-get", "update"], mutate=True)
        for aid in app_ids:
            item = all_items.get(aid)
            if not item or not item.get("apt"):
                continue
            cmd = ["pkexec", "apt-get", "install", "--only-upgrade", "-y", item["apt"]]
            if log: log.append(f"[apt] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)


def uninstall_apps(app_ids: List[str], source: str, log=None):
    apps = load_apps()
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    for aid in app_ids:
        item = all_items.get(aid)
        if not item:
            continue
        if source == "flatpak" and "flatpak" in item:
            ref = item["flatpak"]
            if not _flatpak_installed(ref):
                if log: log.append(f"[uninstall] {item['name']} not installed (Flatpak)\n")
                continue
            cmd = ["flatpak", "uninstall", "-y", ref]
            if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        elif source == "apt" and "apt" in item:
            pkg = item["apt"]
            if not _apt_installed(pkg):
                if log: log.append(f"[uninstall] {item['name']} not installed (APT)\n")
                continue
            cmd = ["pkexec", "apt-get", "remove", "-y", pkg]
            if log: log.append(f"[apt] {' '.join(cmd)}\n")
            run_cmd(cmd, mutate=True)
        else:
            if log: log.append(f"[skip] {item.get('name', aid)} unsupported source {source}\n")
