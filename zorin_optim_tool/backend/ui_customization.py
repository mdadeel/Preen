import os
import shutil
import tarfile

from .utils import run_cmd


def apply_theme_mode(mode: str, log=None):
    # GNOME 42+: org.gnome.desktop.interface color-scheme 'prefer-dark'/'default'
    val = "prefer-dark" if mode == "dark" else "default"
    if log: log.append(f"[gsettings] set color-scheme {val}\n")
    run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", val])


def install_icon_pack(tar_path: str, log=None):
    # Extract into ~/.icons and set with gsettings icon-theme if possible
    dest = os.path.expanduser("~/.icons")
    os.makedirs(dest, exist_ok=True)
    if log: log.append(f"[icons] extract {tar_path} -> {dest}\n")
    try:
        with tarfile.open(tar_path, "r:xz") as tar:
            tar.extractall(dest)
    except tarfile.ReadError:
        if log: log.append("[icons] not a valid .tar.xz file\n")
        return
    # Guess theme dir name as last directory added
    names = [n for n in os.listdir(dest) if os.path.isdir(os.path.join(dest, n))]
    if not names:
        return
    theme = sorted(names, key=lambda x: os.path.getmtime(os.path.join(dest, x)))[-1]
    if log: log.append(f"[icons] set icon theme {theme}\n")
    run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", theme])


def set_rounded_corners(enable: bool, log=None):
    css_dir = os.path.expanduser("~/.config/gtk-3.0")
    os.makedirs(css_dir, exist_ok=True)
    css_path = os.path.join(css_dir, "gtk.css")
    if enable:
        css = """
window, dialog, .background { border-radius: 10px; }
"""
        with open(css_path, "a", encoding="utf-8") as f:
            f.write(css)
        if log: log.append(f"[css] appended rounded corners to {css_path}\n")
    else:
        if os.path.exists(css_path):
            # Remove our line conservatively
            with open(css_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [ln for ln in f if "border-radius" not in ln]
            with open(css_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            if log: log.append(f"[css] removed rounded corners from {css_path}\n")
