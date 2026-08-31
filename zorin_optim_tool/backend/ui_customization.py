import os
import shutil
import tarfile

from .utils import run_cmd


def apply_theme_mode(mode: str, log=None):
    # GNOME 42+: org.gnome.desktop.interface color-scheme 'prefer-dark'/'default'
    val = "prefer-dark" if mode == "dark" else "default"
    if log: log.append(f"[gsettings] set color-scheme {val}\n")
    run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", val])
    
    # GTK Theme toggle
    code, current_theme_raw, _ = run_cmd(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    if code == 0:
        current_theme = current_theme_raw.strip().strip("'\"")
        new_theme = current_theme
        if mode == "dark":
            if not current_theme.lower().endswith("dark"):
                if current_theme.endswith("-Light"):
                    new_theme = current_theme[:-6] + "-Dark"
                elif current_theme.endswith("-light"):
                    new_theme = current_theme[:-6] + "-dark"
                elif current_theme.endswith("Light"):
                    new_theme = current_theme[:-5] + "Dark"
                else:
                    new_theme = current_theme + "-dark"
        else:  # light mode
            if current_theme.lower().endswith("dark"):
                if current_theme.endswith("-Dark"):
                    new_theme = current_theme[:-5] + "-Light"
                elif current_theme.endswith("-dark"):
                    new_theme = current_theme[:-5]
                    if new_theme.endswith("-"):
                        new_theme = new_theme[:-1]
                elif current_theme.endswith("Dark"):
                    new_theme = current_theme[:-4] + "Light"
                else:
                    new_theme = current_theme.replace("-dark", "").replace("-Dark", "").replace("dark", "").replace("Dark", "")
        
        # Test if the new theme exists before applying
        theme_exists = os.path.exists(f"/usr/share/themes/{new_theme}") or os.path.exists(os.path.expanduser(f"~/.themes/{new_theme}"))
        if not theme_exists:
            # Fallback to standard Ubuntu/Zorin themes
            if mode == "dark":
                for fb in ["Yaru-dark", "Adwaita-dark", "ZorinBlue-Dark"]:
                    if os.path.exists(f"/usr/share/themes/{fb}"):
                        new_theme = fb
                        break
            else:
                for fb in ["Yaru", "Adwaita", "ZorinBlue-Light"]:
                    if os.path.exists(f"/usr/share/themes/{fb}"):
                        new_theme = fb
                        break
                    
        if log: log.append(f"[gsettings] set gtk-theme {new_theme}\n")
        run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", new_theme])


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
    
    start_guard = "/* BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
    end_guard = "/* END ZORIN_OPTIMIZER_ROUNDED_CORNERS */\n"
    css_rule = "window, dialog, .background { border-radius: 10px; }\n"
    full_block = f"{start_guard}{css_rule}{end_guard}"

    content = ""
    if os.path.exists(css_path):
        try:
            with open(css_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            pass

    if enable:
        if start_guard in content:
            if log: log.append("[css] rounded corners rule already exists\n")
            return
        try:
            with open(css_path, "a", encoding="utf-8") as f:
                f.write(full_block)
            if log: log.append(f"[css] appended rounded corners to {css_path}\n")
        except Exception as e:
            if log: log.append(f"[css] error writing css: {e}\n")
    else:
        if start_guard in content:
            # Safely strip our block out of the file
            parts = content.split(start_guard, 1)
            before = parts[0]
            after = ""
            if end_guard in parts[1]:
                after = parts[1].split(end_guard, 1)[1]
            else:
                after = parts[1] # fallback
            try:
                with open(css_path, "w", encoding="utf-8") as f:
                    f.write(before + after)
                if log: log.append(f"[css] removed rounded corners from {css_path}\n")
            except Exception as e:
                if log: log.append(f"[css] error clearing css: {e}\n")
        else:
            if log: log.append("[css] rounded corners rule not found in gtk.css\n")
