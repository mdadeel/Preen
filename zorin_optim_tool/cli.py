"""Headless command line interface.

``zorin-optimizer --doctor`` checks the installation without starting GTK, so
it works over SSH and in CI. ``--check-catalog`` validates every app ID and
preset before shipping a release.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Dict, List

from . import __version__
from .backend import apps as apps_backend
from .backend import dashboard


def _capability_rows() -> List[Dict[str, str]]:
    rows = [{
        "name": "Python >= 3.8",
        "status": "ok" if sys.version_info >= (3, 8) else "missing",
        "detail": "{}.{}.{}".format(*sys.version_info[:3]),
        "required": True,
    }]
    for item in dashboard.capabilities():
        rows.append({
            "name": item["name"],
            "status": item["status"],
            "detail": "",
            "required": bool(item["required"]),
        })
    try:
        importlib.import_module("zorin_optim_tool.backend.apps")
        backend_status, backend_detail = "ok", "backend package importable"
    except Exception as exc:  # pragma: no cover - broken installation
        backend_status, backend_detail = "missing", str(exc)
    rows.append({
        "name": "Installed package layout",
        "status": backend_status,
        "detail": backend_detail,
        "required": True,
    })
    return rows


def collect_report() -> Dict:
    problems = list(apps_backend.validate_catalog())
    warnings = []
    # feature_warnings() explains these in plain language, so do not print the
    # same thing twice as a generic "X is missing" line.
    explained_by_notes = {
        "flatpak", "APT / dpkg", "gsettings", "pkexec (polkit)",
        "power-profiles-daemon", "Timeshift",
    }
    for row in _capability_rows():
        if row["status"] != "missing":
            continue
        text = "{} is missing{}".format(row["name"], ": " + row["detail"] if row["detail"] else "")
        # A broken install layout or too-old Python is fatal; absent external
        # binaries only disable the features that need them.
        if row["name"].startswith(("Installed package layout", "Python")):
            problems.append(text)
        elif row["name"] not in explained_by_notes:
            warnings.append(text)
    return {
        "version": __version__,
        "simulate": os.environ.get("ZOPTIM_SIMULATE") == "1",
        "catalog": apps_backend.APPS_JSON,
        "catalog_entries": len(apps_backend.all_apps()),
        "presets": len(apps_backend.load_presets()),
        "capabilities": _capability_rows(),
        "problems": problems,
        "warnings": warnings,
        "feature_warnings": dashboard.feature_warnings(),
    }


def print_report(report: Dict) -> None:
    print("Zorin Optimizer {} - doctor".format(report["version"]))
    print("Catalogue: {} ({} apps, {} presets)".format(
        report["catalog"], report["catalog_entries"], report["presets"]))
    print("-" * 64)
    for row in report["capabilities"]:
        marker = {"ok": "[ OK ]", "optional": "[ -- ]", "missing": "[MISS]"}.get(row["status"], "[ ?? ]")
        detail = (" - " + row["detail"]) if row["detail"] else ""
        print("{} {}{}".format(marker, row["name"], detail))
    print("-" * 64)
    for warning in report["warnings"]:
        print("warning: " + warning)
    for warning in report["feature_warnings"]:
        print("note: " + warning)
    if not report["feature_warnings"] and not report["warnings"]:
        print("All optional tools are available.")
    print("-" * 64)
    if report["problems"]:
        for problem in report["problems"]:
            print("ERROR: " + problem)
        print("Result: FAILED ({} problem(s))".format(len(report["problems"])))
    else:
        print("Result: OK - catalogue and installation are valid.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="zorin-optimizer", add_help=True)
    parser.add_argument("--doctor", action="store_true", help="check installation without starting the GUI")
    parser.add_argument("--check-catalog", action="store_true", help="validate apps.json / presets.json")
    parser.add_argument("--json", action="store_true", help="machine-readable doctor output")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args, _unknown = parser.parse_known_args(argv)

    if args.version:
        print(__version__)
        return 0
    if args.check_catalog:
        problems = apps_backend.validate_catalog()
        if problems:
            for problem in problems:
                print("ERROR: " + problem)
            return 1
        print("Catalogue OK: {} apps, {} presets.".format(
            len(apps_backend.all_apps()), len(apps_backend.load_presets())))
        return 0
    if args.doctor:
        report = collect_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print_report(report)
        return 1 if report["problems"] else 0
    return -1  # let the caller start the GUI
