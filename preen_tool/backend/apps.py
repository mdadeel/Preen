"""Application catalogue, installed-state detection and APT/Flatpak actions.

The old implementation spawned one ``flatpak list`` and one ``dpkg-query``
*per app* on the GUI thread (40+ processes, frozen window), ignored every exit
code, and treated "purge ok not-installed" as installed. This module does two
queries in total, validates the catalogue, batches commands and reports errors.
"""
from __future__ import annotations

import glob
import json
import os
import re
import threading
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import utils
from .utils import (
    Report,
    Outcome,
    ensure_flathub,
    fail,
    format_cmd,
    has_command,
    is_simulate,
    ok,
    run_cmd,
)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
APPS_JSON = os.path.join(CONFIG_DIR, "apps.json")
PRESETS_JSON = os.path.join(CONFIG_DIR, "presets.json")

FLATPAK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
APT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?$")
FLATHUB_REPO = "flathub"

# Removing any of these can leave a Zorin/Ubuntu machine unbootable. Refuse
# them even if the user selects them in "Manage Apps".
ESSENTIAL_APT_PACKAGES = frozenset({
    "apt", "dpkg", "bash", "dash", "coreutils", "sudo", "polkitd", "policykit-1",
    "python3", "python3-minimal", "perl", "perl-base", "systemd", "dbus",
    "gnome-shell", "gnome-session", "gnome-control-center", "gdm3",
    "network-manager", "xorg", "xserver-xorg", "mesa-vulkan-drivers",
    "nautilus", "ubuntu-desktop", "ubuntu-minimal", "zorin-os-desktop",
    "zorin-appearance", "flatpak", "gsettings-desktop-schemas",
})

_catalog_cache: Optional[Dict[str, List[Dict]]] = None
_presets_cache: Optional[Dict[str, List[str]]] = None
_catalog_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def load_apps() -> Dict[str, List[Dict]]:
    global _catalog_cache
    with _catalog_lock:
        if _catalog_cache is None:
            try:
                with open(APPS_JSON, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("apps.json must be an object")
                _catalog_cache = data
            except (OSError, ValueError) as exc:
                raise RuntimeError("Cannot read app catalogue {}: {}".format(APPS_JSON, exc))
        return _catalog_cache


def load_presets() -> Dict[str, List[str]]:
    global _presets_cache
    with _catalog_lock:
        if _presets_cache is None:
            try:
                with open(PRESETS_JSON, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    raise ValueError("presets.json must be an object")
                _presets_cache = data
            except (OSError, ValueError):
                _presets_cache = {}
        return _presets_cache


def all_apps() -> Dict[str, Dict]:
    return {item["id"]: item for group in load_apps().values() for item in group}


def validate_catalog() -> List[str]:
    """Return a list of catalogue problems (empty means healthy)."""
    problems: List[str] = []
    try:
        catalogue = load_apps()
    except RuntimeError as exc:
        return [str(exc)]
    seen: Set[str] = set()
    for category, entries in catalogue.items():
        if not isinstance(entries, list):
            problems.append("{}: not a list".format(category))
            continue
        for item in entries:
            app_id = item.get("id")
            name = item.get("name")
            if not app_id or not name:
                problems.append("{}: entry missing id/name: {!r}".format(category, item))
                continue
            if app_id in seen:
                problems.append("duplicate id: {}".format(app_id))
            seen.add(app_id)
            if not item.get("apt") and not item.get("flatpak"):
                problems.append("{}: no apt or flatpak package".format(app_id))
            for ref in as_list(item.get("flatpak")):
                if not FLATPAK_ID_RE.match(ref):
                    problems.append("{}: invalid flatpak id {!r}".format(app_id, ref))
            for pkg in as_list(item.get("apt")):
                if not APT_NAME_RE.match(pkg):
                    problems.append("{}: invalid apt package {!r}".format(app_id, pkg))
    for preset, ids in load_presets().items():
        for app_id in ids:
            if app_id not in seen:
                problems.append("preset {!r} references unknown id {!r}".format(preset, app_id))
    return problems


def as_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def is_protected(pkg: str) -> bool:
    return pkg.split(":")[0] in ESSENTIAL_APT_PACKAGES


# ---------------------------------------------------------------------------
# Installed state (two subprocesses total, cached until a mutation)
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_state_cache: Optional[Tuple[Set[str], Set[str], List[str]]] = None


def invalidate_state() -> None:
    global _state_cache
    with _state_lock:
        _state_cache = None


def get_installed_state(refresh: bool = False) -> Tuple[Set[str], Set[str], List[str]]:
    """Return (flatpak_ids, apt_packages, warnings)."""
    global _state_cache
    with _state_lock:
        if _state_cache is not None and not refresh:
            return _state_cache
        flatpaks, apt_packages, warnings = set(), set(), []

        if has_command("flatpak"):
            result = run_cmd(["flatpak", "list", "--app", "--columns=application"])
            if result.ok:
                flatpaks = {line.strip() for line in result.out.splitlines() if line.strip()}
            else:
                warnings.append("flatpak list failed: {}".format(result.detail(200)))
        else:
            warnings.append("flatpak is not installed")

        if has_command("dpkg-query"):
            fmt = "${Package}\\t${binary:Package}\\t${Status}\\n"
            result = run_cmd(["dpkg-query", "-W", "-f=" + fmt])
            if not result.ok:  # older dpkg
                result = run_cmd(["dpkg-query", "-W", "-f=${Package}\\t${Status}\\n"])
            if result.ok:
                for line in result.out.splitlines():
                    parts = line.split("\t")
                    status = parts[-1].split()
                    # "install ok installed" == installed.
                    # "purge ok not-installed" must NOT match on a substring.
                    if len(status) >= 3 and status[2] == "installed":
                        for candidate in parts[:-1]:
                            pkg = candidate.strip()
                            if pkg:
                                apt_packages.add(pkg)
                                if ":" in pkg:
                                    apt_packages.add(pkg.split(":")[0])
            else:
                warnings.append("dpkg-query failed: {}".format(result.detail(200)))
        else:
            warnings.append("dpkg-query is not installed")

        _state_cache = (flatpaks, apt_packages, warnings)
        return _state_cache


def _flatpak_installed(ref: str) -> bool:
    return ref in get_installed_state()[0]


def _apt_installed(pkg: str) -> bool:
    return pkg in get_installed_state()[1]


def installed_formats(item: Dict) -> List[Tuple[str, str]]:
    """Which package formats of a catalogue entry are actually installed."""
    found: List[Tuple[str, str]] = []
    for ref in as_list(item.get("flatpak")):
        if _flatpak_installed(ref):
            found.append(("flatpak", ref))
    for pkg in as_list(item.get("apt")):
        if _apt_installed(pkg):
            found.append(("apt", pkg))
    return found


def get_status_label_map() -> Dict[str, str]:
    status: Dict[str, str] = {}
    flatpaks, apt_packages, warnings = get_installed_state()
    flat_problem = next((w for w in warnings if w.startswith("flatpak ")), "")
    apt_problem = next((w for w in warnings if w.startswith("dpkg-query ")), "")
    for item in all_apps().values():
        formats = []
        if any(ref in flatpaks for ref in as_list(item.get("flatpak"))):
            formats.append("Flatpak")
        if any(pkg in apt_packages for pkg in as_list(item.get("apt"))):
            formats.append("APT")
        if formats:
            label = "Installed ({})".format(", ".join(formats))
        else:
            problems = ([flat_problem] if item.get("flatpak") and flat_problem else [])
            problems += ([apt_problem] if item.get("apt") and apt_problem else [])
            # A missing/failed scanner cannot prove that a package is absent.
            label = ("Error" if any("failed" in p for p in problems) else "Unavailable") if problems else "Not installed"
        status[item["id"]] = label
    return status


def get_status_map(source: str) -> Dict[str, bool]:
    """Backwards compatible per-source status map."""
    result = {}
    flatpaks, apt_packages, _ = get_installed_state()
    installed = flatpaks if source == "flatpak" else apt_packages
    key = "flatpak" if source == "flatpak" else "apt"
    for app_id, item in all_apps().items():
        result[app_id] = any(ref in installed for ref in as_list(item.get(key)))
    return result


# ---------------------------------------------------------------------------
# Scanners for "Manage Apps"
# ---------------------------------------------------------------------------
def list_installed_flatpak(warnings=None, log=None) -> List[Dict]:
    if not has_command("flatpak"):
        if warnings is not None:
            warnings.append("Flatpak is not installed")
        if log:
            log.append("[warning] Flatpak is not installed; its applications cannot be scanned.\n")
        return []
    result = run_cmd(["flatpak", "list", "--app", "--columns=application,name"], quiet=True)
    if not result.ok:
        message = "Flatpak scan failed (exit {}): {}".format(
            result.code, result.err or result.out or "no output")
        if warnings is not None:
            warnings.append(message)
        if log:
            log.append("[warning] " + message.rstrip() + "\n")
    items: List[Dict] = []
    if result.ok:
        for line in result.out.splitlines():
            parts = [p.strip() for p in line.split("\t")]
            if not parts or not parts[0]:
                continue
            items.append({
                "source": "flatpak",
                "id": parts[0],
                "name": parts[1] if len(parts) > 1 and parts[1] else parts[0],
                "protected": False,
            })
    return items


def list_installed_apt(warnings=None, log=None) -> List[Dict]:
    """List graphical APT applications via their .desktop launchers.

    One ``dpkg -S`` call resolves every launcher to its owning package. The
    old glob+per-file approach misparsed multiarch owners and produced
    thousands of library rows.
    """
    desktop_files = sorted(glob.glob("/usr/share/applications/*.desktop"))
    if not has_command("dpkg"):
        if warnings is not None:
            warnings.append("dpkg is not installed")
        if log:
            log.append("[warning] dpkg is not installed; graphical APT applications cannot be scanned.\n")
        return []
    if not desktop_files:
        return []

    owners: Dict[str, str] = {}
    result = run_cmd(["dpkg", "-S"] + desktop_files, quiet=True)
    if result.code not in (0, 1):
        message = "APT application scan failed (exit {}): {}".format(
            result.code, result.err or result.out or "no output")
        if warnings is not None:
            warnings.append(message)
        if log:
            log.append("[warning] " + message.rstrip() + "\n")
    if result.code in (0, 1):  # 1 = at least one path is not owned by a package
        for line in result.out.splitlines():
            if ": " not in line:
                continue
            owner_part, path = line.rsplit(": ", 1)
            if not path.startswith("/") or owner_part.startswith(("diversion", "locally")):
                continue
            owner = owner_part.split(",")[0].strip()
            pkg = owner.split(":")[0].strip()
            if pkg:
                owners[path] = pkg

    items: List[Dict] = []
    seen: Set[str] = set()
    for path in desktop_files:
        pkg = owners.get(path)
        if not pkg or pkg in seen:
            continue
        info = utils.parse_desktop_file(path)
        if str(info["type"]).lower() != "application" or info["no_display"] or info["hidden"]:
            continue
        seen.add(pkg)
        items.append({
            "source": "apt",
            "id": pkg,
            "name": str(info["name"]),
            "protected": is_protected(pkg),
        })
    items.sort(key=lambda x: x["name"].lower())
    return items


# ---------------------------------------------------------------------------
# Command construction helpers
# ---------------------------------------------------------------------------
def _apt_script(*commands: Sequence[str]) -> str:
    return " && ".join("DEBIAN_FRONTEND=noninteractive " + format_cmd(c) for c in commands)


def _check_source(source: str) -> str:
    source = (source or "flatpak").lower()
    if source not in ("flatpak", "apt"):
        raise ValueError("Unknown package source: {!r}".format(source))
    return source


def _resolve_selection(app_ids: Iterable[str], source: str, mode: str
                       ) -> Tuple[List[str], List[str], List[str]]:
    """Return (flatpak_refs, apt_packages, notes).

    install: prefer the selected source, fall back to the other one.
    update/uninstall: act on formats that are actually installed.
    """
    source = _check_source(source)
    catalogue = all_apps()
    flatpaks: List[str] = []
    apts: List[str] = []
    notes: List[str] = []
    for app_id in app_ids:
        item = catalogue.get(app_id)
        if not item:
            notes.append("unknown app id {!r}, skipped".format(app_id))
            continue

        if mode == "install":
            preferred, other = (("flatpak", "apt") if source == "flatpak" else ("apt", "flatpak"))
            chosen = item.get(preferred) or item.get(other)
            if not chosen:
                continue
            kind = preferred if item.get(preferred) else other
            for name in as_list(chosen):
                already = _flatpak_installed(name) if kind == "flatpak" else _apt_installed(name)
                if already:
                    notes.append("{} is already installed ({})".format(item["name"], kind))
                else:
                    (flatpaks if kind == "flatpak" else apts).append(name)
            if not item.get(preferred) and item.get(other):
                notes.append("{} has no {} package; using {}".format(item["name"], preferred, other))
        else:
            formats = installed_formats(item)
            if not formats:
                notes.append("{} is not installed; nothing to {}".format(item["name"], mode))
                continue
            for kind, name in formats:
                if kind == "apt" and mode == "uninstall" and is_protected(name):
                    notes.append("{} ({}) is essential and cannot be removed here".format(item["name"], name))
                    continue
                (flatpaks if kind == "flatpak" else apts).append(name)
    # de-duplicate, preserve order
    return list(dict.fromkeys(flatpaks)), list(dict.fromkeys(apts)), notes


def _validate_entries(entries: Iterable[Dict]) -> Tuple[List[str], List[str], List[str]]:
    """Validate scanner rows before they become command arguments."""
    flatpaks, apts, notes = [], [], []
    for entry in entries:
        source = entry.get("source")
        ident = str(entry.get("id", ""))
        if source == "flatpak" and FLATPAK_ID_RE.match(ident):
            flatpaks.append(ident)
        elif source == "apt" and APT_NAME_RE.match(ident):
            if is_protected(ident):
                notes.append("{} is essential and cannot be removed here".format(ident))
            else:
                apts.append(ident)
        else:
            notes.append("ignored invalid entry {!r}".format(entry))
    return list(dict.fromkeys(flatpaks)), list(dict.fromkeys(apts)), notes


def _run_batches(report: Report, flatpaks: Sequence[str], apts: Sequence[str],
                 action: str, *, ensure_remote: bool = False) -> None:
    if flatpaks:
        remote_ready = not ensure_remote or ensure_flathub(log=report.log, mutate=True)
        if not remote_ready and not is_simulate():
            report.commands += 1
            report.failures.append("flathub remote is not configured; Flatpak install skipped")
        else:
            if action == "install":
                argv = ["flatpak", "install", "-y", "--noninteractive", FLATHUB_REPO] + list(flatpaks)
            elif action == "remove":
                argv = ["flatpak", "uninstall", "-y", "--noninteractive"] + list(flatpaks)
            else:
                argv = ["flatpak", "update", "-y", "--noninteractive"] + list(flatpaks)
            report.run(argv, mutate=True)

    if apts:
        if action == "install":
            commands: List[Sequence[str]] = [
                ["apt-get", "update"],
                ["apt-get", "install", "-y"] + list(apts),
            ]
        elif action == "remove":
            commands = [["apt-get", "remove", "-y"] + list(apts)]
        else:
            commands = [
                ["apt-get", "update"],
                ["apt-get", "install", "--only-upgrade", "-y"] + list(apts),
            ]
        script = _apt_script(*commands)
        report.run(["bash", "-c", script], use_pkexec=True, mutate=True,
                   timeout=utils.DEFAULT_TIMEOUT)


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------
def _selection_scan_failures(app_ids: List[str], source: str, mode: str) -> List[str]:
    """Do not mistake a failed relevant package query for an absent package."""
    source = _check_source(source)
    _flatpaks, _apts, warnings = get_installed_state()
    problems = {
        "flatpak": [w for w in warnings if w.startswith("flatpak list failed")],
        "apt": [w for w in warnings if w.startswith("dpkg-query failed") or
                (w.startswith("dpkg-query is not installed") and has_command("apt-get"))],
    }
    relevant = set()
    catalogue = all_apps()
    for app_id in app_ids:
        item = catalogue.get(app_id)
        if not item:
            continue
        if mode == "install":
            other = "apt" if source == "flatpak" else "flatpak"
            chosen = source if item.get(source) else other if item.get(other) else None
            if chosen:
                relevant.add(chosen)
        else:
            relevant.update(kind for kind in ("flatpak", "apt") if item.get(kind))
    return [warning for kind in ("flatpak", "apt") if kind in relevant
            for warning in problems[kind]]


def install_apps(app_ids: List[str], source: str, log=None) -> Outcome:
    if not app_ids:
        return fail("No apps selected.")
    if not any(app_id in all_apps() for app_id in app_ids):
        return fail("No recognised apps selected.")
    problems = _selection_scan_failures(app_ids, source, "install")
    if problems:
        return fail("Cannot determine installed state; refresh package status and try again.", *problems)
    report = Report(log)
    flatpaks, apts, notes = _resolve_selection(app_ids, source, "install")
    for note in notes:
        report.note("[install] " + note)
    if not flatpaks and not apts:
        return ok("Nothing to install. Everything selected is already installed.")
    _run_batches(report, flatpaks, apts, "install", ensure_remote=bool(flatpaks))
    outcome = report.finish(
        "Installed {} Flatpak app(s) and {} APT package(s).".format(len(flatpaks), len(apts)),
        "Install finished with errors",
    )
    invalidate_state()
    return outcome


def update_apps(app_ids: List[str], source: str, log=None) -> Outcome:
    _check_source(source)
    if not app_ids:
        return fail("No apps selected.")
    if not any(app_id in all_apps() for app_id in app_ids):
        return fail("No recognised apps selected.")
    problems = _selection_scan_failures(app_ids, source, "update")
    if problems:
        return fail("Cannot determine installed state; refresh package status and try again.", *problems)
    report = Report(log)
    flatpaks, apts, notes = _resolve_selection(app_ids, source, "update")
    for note in notes:
        report.note("[update] " + note)
    if not flatpaks and not apts:
        return ok("Nothing to update. None of the selected apps are installed.")
    _run_batches(report, flatpaks, apts, "upgrade")
    invalidate_state()
    return report.finish(
        "Updated {} Flatpak app(s) and {} APT package(s).".format(len(flatpaks), len(apts)),
        "Update finished with errors",
    )


def uninstall_apps(app_ids: List[str], source: str, log=None) -> Outcome:
    _check_source(source)
    if not app_ids:
        return fail("No apps selected.")
    if not any(app_id in all_apps() for app_id in app_ids):
        return fail("No recognised apps selected.")
    problems = _selection_scan_failures(app_ids, source, "uninstall")
    if problems:
        return fail("Cannot determine installed state; refresh package status and try again.", *problems)
    report = Report(log)
    flatpaks, apts, notes = _resolve_selection(app_ids, source, "uninstall")
    for note in notes:
        report.note("[uninstall] " + note)
    if not flatpaks and not apts:
        return ok("Nothing to uninstall.")
    _run_batches(report, flatpaks, apts, "remove")
    invalidate_state()
    return report.finish(
        "Uninstalled {} Flatpak app(s) and {} APT package(s).".format(len(flatpaks), len(apts)),
        "Uninstall finished with errors",
    )


def update_all(source: str, log=None) -> Outcome:
    source = _check_source(source)
    report = Report(log)
    if source == "flatpak":
        report.run(["flatpak", "update", "-y", "--noninteractive"], mutate=True)
        outcome = report.finish("All Flatpak apps updated.", "Flatpak update failed")
    else:
        script = _apt_script(["apt-get", "update"], ["apt-get", "upgrade", "-y"])
        report.run(["bash", "-c", script], use_pkexec=True, mutate=True,
                   timeout=utils.DEFAULT_TIMEOUT)
        outcome = report.finish("All APT packages updated.", "APT upgrade failed")
    invalidate_state()
    return outcome


def uninstall_installed(entries: List[Dict], log=None) -> Outcome:
    return _operate_installed(entries, "remove", log)


def update_installed(entries: List[Dict], log=None) -> Outcome:
    return _operate_installed(entries, "upgrade", log)


def _operate_installed(entries: List[Dict], action: str, log) -> Outcome:
    if not entries:
        return fail("No installed apps selected.")
    report = Report(log)
    flatpaks, apts, notes = _validate_entries(entries)
    for note in notes:
        report.note("[" + action + "] " + note)
    if not flatpaks and not apts:
        return fail("Nothing safe to " + ("uninstall." if action == "remove" else "update."))
    _run_batches(report, flatpaks, apts, action)
    invalidate_state()
    verb = "Uninstalled" if action == "remove" else "Updated"
    return report.finish(
        "{} {} Flatpak app(s) and {} APT package(s).".format(verb, len(flatpaks), len(apts)),
        verb + " finished with errors",
    )
