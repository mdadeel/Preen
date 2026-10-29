"""Persistent user preferences.

Stored in ``~/.config/preen/settings.json``. Everything is validated on read
so a corrupted or hand-edited file can never crash the GUI. Settings written
by 0.2.x under ``~/.config/zorin-optimizer/`` are migrated on first load.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

CONFIG_DIR = os.path.expanduser("~/.config/preen")
LEGACY_CONFIG_DIR = os.path.expanduser("~/.config/zorin-optimizer")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

VALID_SOURCES = ("flatpak", "apt")
VALID_APPEARANCE = ("system", "light", "dark")
VALID_REFRESH = (0, 10, 15, 30, 60)
VALID_PAGES = ("dashboard", "install", "manage", "appimages", "optimize",
               "customize", "backup", "logs", "deepclean", "services", "drivers")

DEFAULTS: Dict[str, Any] = {
    "simulate_on_startup": False,
    "default_source": "flatpak",
    "appearance_mode": "system",
    "confirm_destructive": True,
    "show_dependency_warnings": True,
    "auto_refresh_seconds": 15,
    "page_on_startup": "dashboard",
}

# A preference update may be requested by the worker while the Preferences
# dialog is open. Protect read/modify/write and the shared temporary file.
_lock = threading.RLock()


def defaults() -> Dict[str, Any]:
    return dict(DEFAULTS)


def validate(values: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce anything unexpected back to a safe, known value."""
    clean = defaults()
    if not isinstance(values, dict):
        return clean
    for key in ("simulate_on_startup", "confirm_destructive",
                "show_dependency_warnings"):
        if key in values:
            clean[key] = bool(values[key])
    source = values.get("default_source")
    if source in VALID_SOURCES:
        clean["default_source"] = source
    appearance = values.get("appearance_mode")
    if appearance in VALID_APPEARANCE:
        clean["appearance_mode"] = appearance
    page = values.get("page_on_startup")
    if page in VALID_PAGES:
        clean["page_on_startup"] = page
    try:
        refresh = int(values.get("auto_refresh_seconds", clean["auto_refresh_seconds"]))
    except (TypeError, ValueError):
        refresh = clean["auto_refresh_seconds"]
    clean["auto_refresh_seconds"] = refresh if refresh in VALID_REFRESH else 15
    return clean


def _migrate_legacy_dir() -> None:
    """Move 0.2.x settings into ~/.config/preen (once; never overwrite)."""
    if os.path.exists(CONFIG_DIR) or not os.path.isdir(LEGACY_CONFIG_DIR):
        return
    try:
        os.makedirs(os.path.dirname(CONFIG_DIR), exist_ok=True)
        os.rename(LEGACY_CONFIG_DIR, CONFIG_DIR)
    except OSError:
        pass


def load() -> Dict[str, Any]:
    with _lock:
        _migrate_legacy_dir()
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return defaults()
    return validate(data)


def save(values: Dict[str, Any]) -> bool:
    clean = validate(values)
    with _lock:
        tmp = SETTINGS_PATH + ".tmp"
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(clean, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, SETTINGS_PATH)
            return True
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def update(changes: Dict[str, Any]) -> bool:
    """Atomically merge preferences without resetting unrelated values."""
    with _lock:
        values = load()
        values.update(changes)
        return save(values)


def set_value(key: str, value: Any) -> bool:
    return update({key: value})


def reset() -> bool:
    return save(defaults())
