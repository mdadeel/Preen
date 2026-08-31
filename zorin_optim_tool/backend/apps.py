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
    import glob
    # 1. Glob all .desktop files
    desktop_files = glob.glob("/usr/share/applications/*.desktop")
    if not desktop_files:
        return []
    
    # 2. Get packages owning those desktop files in a single dpkg query
    desktop_to_pkg = {}
    try:
        code, out, _ = run_cmd(["dpkg", "-S"] + desktop_files)
        if code in (0, 1):
            for line in out.splitlines():
                if ":" in line:
                    parts = line.split(":", 1)
                    pkg_names = parts[0].strip()
                    file_path = parts[1].strip()
                    # A file can be owned by multiple packages (comma-separated), take the first one
                    pkg = pkg_names.split(",")[0].strip()
                    desktop_to_pkg[file_path] = pkg
    except Exception:
        pass

    # 3. Parse desktop files to get human-readable Name
    items = []
    seen_packages = set()
    for path in desktop_files:
        pkg = desktop_to_pkg.get(path)
        if not pkg:
            continue
        if pkg in seen_packages:
            continue
        
        name = pkg
        is_app = False
        no_display = False
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                in_entry = False
                for line in f:
                    line = line.strip()
                    if line == "[Desktop Entry]":
                        in_entry = True
                    elif line.startswith("[") and line.endswith("]"):
                        in_entry = False
                    elif in_entry:
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1].strip()
                        elif line.startswith("Type="):
                            is_app = (line.split("=", 1)[1].strip().lower() == "application")
                        elif line.startswith("NoDisplay="):
                            no_display = (line.split("=", 1)[1].strip().lower() == "true")
                        elif line.startswith("Hidden="):
                            no_display = no_display or (line.split("=", 1)[1].strip().lower() == "true")
        except Exception:
            continue
            
        if is_app and not no_display:
            seen_packages.add(pkg)
            items.append({"source": "apt", "id": pkg, "name": name})
            
    items.sort(key=lambda x: x["name"].lower())
    return items


def uninstall_installed(entries: List[Dict], log=None):
    flatpaks = []
    apts = []
    for it in entries:
        src = it.get("source")
        ident = it.get("id")
        if src == "flatpak":
            flatpaks.append(ident)
        elif src == "apt":
            apts.append(ident)
    
    if flatpaks:
        cmd = ["flatpak", "uninstall", "-y"] + flatpaks
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    if apts:
        cmd = ["pkexec", "apt-get", "remove", "-y"] + apts
        if log: log.append(f"[apt] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


def update_installed(entries: List[Dict], log=None):
    flatpaks = []
    apts = []
    for it in entries:
        src = it.get("source")
        ident = it.get("id")
        if src == "flatpak":
            flatpaks.append(ident)
        elif src == "apt":
            apts.append(ident)
            
    if flatpaks:
        cmd = ["flatpak", "update", "-y"] + flatpaks
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    if apts:
        run_cmd(["pkexec", "apt-get", "update"], mutate=True)
        cmd = ["pkexec", "apt-get", "install", "--only-upgrade", "-y"] + apts
        if log: log.append(f"[apt] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


def install_apps(app_ids: List[str], source: str, log=None):
    ensure_flathub()
    apps = load_apps()
    # Flatten list
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    
    flatpaks_to_install = []
    apts_to_install = []
    
    for aid in app_ids:
        item = all_items.get(aid)
        if not item:
            continue
        
        has_flat = bool(item.get("flatpak"))
        has_apt = bool(item.get("apt"))
        
        if source == "flatpak":
            if has_flat:
                ref = item["flatpak"]
                if not _flatpak_installed(ref):
                    flatpaks_to_install.append(ref)
                else:
                    if log: log.append(f"[install] {item['name']} already installed (Flatpak)\n")
            elif has_apt:
                pkg = item["apt"]
                if not _apt_installed(pkg):
                    apts_to_install.append(pkg)
                else:
                    if log: log.append(f"[install] {item['name']} already installed (APT)\n")
        else:  # source == "apt"
            if has_apt:
                pkg = item["apt"]
                if not _apt_installed(pkg):
                    apts_to_install.append(pkg)
                else:
                    if log: log.append(f"[install] {item['name']} already installed (APT)\n")
            elif has_flat:
                ref = item["flatpak"]
                if not _flatpak_installed(ref):
                    flatpaks_to_install.append(ref)
                else:
                    if log: log.append(f"[install] {item['name']} already installed (Flatpak)\n")
                    
    if flatpaks_to_install:
        cmd = ["flatpak", "install", "-y", "flathub"] + flatpaks_to_install
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    if apts_to_install:
        run_cmd(["pkexec", "apt-get", "update"], mutate=True)
        cmd = ["pkexec", "apt-get", "install", "-y"] + apts_to_install
        if log: log.append(f"[apt] install {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


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
    
    flatpaks_to_update = []
    apts_to_update = []
    
    for aid in app_ids:
        item = all_items.get(aid)
        if not item:
            continue
            
        has_flat = bool(item.get("flatpak"))
        has_apt = bool(item.get("apt"))
        
        if source == "flatpak":
            if has_flat:
                flatpaks_to_update.append(item["flatpak"])
            elif has_apt:
                apts_to_update.append(item["apt"])
        else:  # source == "apt"
            if has_apt:
                apts_to_update.append(item["apt"])
            elif has_flat:
                flatpaks_to_update.append(item["flatpak"])
                
    if flatpaks_to_update:
        cmd = ["flatpak", "update", "-y"] + flatpaks_to_update
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    if apts_to_update:
        run_cmd(["pkexec", "apt-get", "update"], mutate=True)
        cmd = ["pkexec", "apt-get", "install", "--only-upgrade", "-y"] + apts_to_update
        if log: log.append(f"[apt] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


def uninstall_apps(app_ids: List[str], source: str, log=None):
    apps = load_apps()
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    
    flatpaks_to_uninstall = []
    apts_to_uninstall = []
    
    for aid in app_ids:
        item = all_items.get(aid)
        if not item:
            continue
            
        has_flat = bool(item.get("flatpak"))
        has_apt = bool(item.get("apt"))
        
        if source == "flatpak":
            if has_flat:
                ref = item["flatpak"]
                if _flatpak_installed(ref):
                    flatpaks_to_uninstall.append(ref)
                else:
                    if log: log.append(f"[uninstall] {item['name']} not installed (Flatpak)\n")
            elif has_apt:
                pkg = item["apt"]
                if _apt_installed(pkg):
                    apts_to_uninstall.append(pkg)
                else:
                    if log: log.append(f"[uninstall] {item['name']} not installed (APT)\n")
        else:  # source == "apt"
            if has_apt:
                pkg = item["apt"]
                if _apt_installed(pkg):
                    apts_to_uninstall.append(pkg)
                else:
                    if log: log.append(f"[uninstall] {item['name']} not installed (APT)\n")
            elif has_flat:
                ref = item["flatpak"]
                if _flatpak_installed(ref):
                    flatpaks_to_uninstall.append(ref)
                else:
                    if log: log.append(f"[uninstall] {item['name']} not installed (Flatpak)\n")
                    
    if flatpaks_to_uninstall:
        cmd = ["flatpak", "uninstall", "-y"] + flatpaks_to_uninstall
        if log: log.append(f"[flatpak] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)
    if apts_to_uninstall:
        cmd = ["pkexec", "apt-get", "remove", "-y"] + apts_to_uninstall
        if log: log.append(f"[apt] {' '.join(cmd)}\n")
        run_cmd(cmd, mutate=True)


def get_status_label_map() -> Dict[str, str]:
    apps = load_apps()
    all_items = {item["id"]: item for cat in apps.values() for item in cat}
    status = {}
    for aid, item in all_items.items():
        formats = []
        if item.get("flatpak") and _flatpak_installed(item["flatpak"]):
            formats.append("Flatpak")
        if item.get("apt") and _apt_installed(item["apt"]):
            formats.append("APT")
        if formats:
            status[aid] = f"Installed ({', '.join(formats)})"
        else:
            status[aid] = "Not installed"
    return status
