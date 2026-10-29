"""A fake Linux userspace for the tests.

Creates executable stand-ins for flatpak, dpkg, gsettings, pkexec, swapon,
powerprofilesctl and timeshift. Every invocation is appended to a JSONL log so
tests can assert on the *exact* commands the backend would have run, without
touching the real machine.
"""
from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

DISPATCHER = r'''#!/usr/bin/env python3
"""One script, many command names (symlinked)."""
import json
import os
import sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
log_path = os.environ.get("ZOPT_FAKE_LOG", "")
state_path = os.environ.get("ZOPT_FAKE_STATE", "")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cmd": name, "args": args}) + "\n")
try:
    with open(state_path, "r", encoding="utf-8") as handle:
        state = json.load(handle)
except Exception:
    state = {}

out, err, code = "", "", 0

if name == "flatpak":
    sub = args[0] if args else ""
    if sub == "list":
        want_names = any("--columns=application,name" in a for a in args)
        for ref in state.get("flatpaks", []):
            label = state.get("flatpak_names", {}).get(ref, ref)
            out += ref + ("\t" + label if want_names else "") + "\n"
    elif sub == "remotes":
        out = "flathub\n" if state.get("flathub", True) else ""
    elif sub == "remote-ls" and "--updates" in args:
        if state.get("flatpak_remote_ls_fail"):
            code = 1
        else:
            out = "".join(ref + "\n" for ref in state.get("flatpak_updates", []))
    elif sub in ("install", "uninstall", "update", "remote-add"):
        pass
    else:
        code = 1
elif name == "apt":
    if args and args[0] == "list" and "--upgradable" in args:
        for row in state.get("apt_upgradable", []):
            pkg = row if isinstance(row, str) else row.get("name", "")
            out += "{}/noble 1.2-3 all [upgradable from: 1.2-2]\n".format(pkg)
    else:
        code = 1
elif name == "dpkg-query":
    for pkg, status in sorted(state.get("apt", {}).items()):
        out += "{}\t{}\t{}\n".format(pkg, pkg, status)
elif name == "dpkg":
    if args and args[0] == "-S":
        if state.get("dpkg_S_batch_fail") and len(args) > 2:
            err, code = "dpkg: error: simulated batch ownership failure", 2
        else:
            owners = state.get("owners", {})
            for path in args[1:]:
                owner = owners.get(path)
                if owner:
                    out += "{}: {}\n".format(owner, path)
                else:
                    code = 1
    else:
        code = 1
elif name == "gsettings":
    action = args[0] if args else ""
    defaults = {"color-scheme": "default", "gtk-theme": "Adwaita",
                "enable-animations": "true", "text-scaling-factor": "1.0",
                "icon-theme": "Adwaita"}
    keys = state.get("gsettings_keys", list(defaults))
    if action == "list-keys":
        out = "\n".join(keys) + "\n"
    elif action in ("get", "set") and len(args) >= 3:
        key = args[2]
        if key not in keys:
            err, code = "No such key '{}'".format(key), 1
        elif action == "get" and state.get("gsettings_fail_get") == key:
            err, code = "Could not read {}".format(key), 1
        elif action == "get":
            out = "'" + str(state.get("gsettings", {}).get(key, defaults.get(key, ""))) + "'\n"
        elif state.get("gsettings_fail_set") == key:
            err, code = "Could not write {}".format(key), 1
        else:
            state.setdefault("gsettings", {})[key] = args[3]
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
    else:
        code = 1
elif name == "snap":
    sub = args[0] if args else ""
    if sub == "list" and "--all" in args:
        out = "Name  Version  Rev  Tracking  Publisher  Notes\n"
        for snap_name, info in sorted(state.get("snaps", {}).items()):
            info = info if isinstance(info, dict) else {}
            out += "{}  {}  101  latest/stable  publisher  {}\n".format(
                snap_name, info.get("version", "1.0"), info.get("notes", "-"))
    elif sub == "refresh" and "--list" in args:
        out = "Name  Version  Rev  Size  Publisher  Notes\n"
        for snap_name, info in sorted(state.get("snap_updates", {}).items()):
            out += "{}  {}  102  100MB  publisher  {}\n".format(
                snap_name, info if isinstance(info, str) else info.get("version", "2.0"),
                "latest/stable" if not isinstance(info, str) else "")
    elif sub in ("refresh", "remove", "install"):
        pass  # never actually mutate; the bash/pkexec fake logs those
    else:
        code = 1
elif name == "swapon":
    out = "\n".join(state.get("swap", [])) + "\n"
elif name == "powerprofilesctl":
    if args and args[0] == "get":
        out = state.get("power", "balanced") + "\n"
elif name == "timeshift":
    if args and args[0] == "--list":
        out = state.get("timeshift_list", "")
        err = state.get("timeshift_error", "")
        code = state.get("timeshift_exit", 0)
    # Never execute a privileged snapshot in tests.
elif name in ("pkexec", "bash", "sh", "timeshift-gtk", "timeshift-launcher"):
    pass  # deliberately do NOT execute privileged scripts in tests
elif name == "failcmd":
    out, err, code = "", "boom: something broke", 3
else:
    err, code = "unknown fake command " + name, 127

sys.stdout.write(out)
sys.stderr.write(err)
sys.exit(code)
'''

COMMANDS = (
    "flatpak", "dpkg-query", "dpkg", "apt", "gsettings", "swapon",
    "powerprofilesctl", "pkexec", "bash", "timeshift", "snap",
    "timeshift-gtk", "timeshift-launcher", "failcmd",
)

MUTATING = {"pkexec", "bash", "timeshift", "timeshift-gtk", "timeshift-launcher"}


class FakeSystem:
    def __init__(self, root):
        self.root = Path(root)
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.log_path = self.root / "commands.jsonl"
        self.home = self.root / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.config_dir = self.home / ".config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.icons_dir = self.home / ".icons"
        self.icons_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.touch()

        script = self.bin / "_zoptim_fake.py"
        script.write_text(DISPATCHER, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        for name in COMMANDS:
            link = self.bin / name
            if not link.exists():
                link.symlink_to(script)

        self.state = {
            "flatpaks": [],
            "flatpak_names": {},
            "flathub": True,
            "apt": {},
            "owners": {},
            "snaps": {},
            "snap_updates": {},
            "flatpak_updates": [],
            "apt_upgradable": [],
            "flatpak_remote_ls_fail": False,
            "gsettings": {},
            "swap": [],
            "power": "balanced",
        }
        self._write_state()

    def _write_state(self):
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")

    def update(self, **kwargs):
        self.state.update(kwargs)
        self._write_state()
        return self

    def clear_log(self):
        self.log_path.write_text("", encoding="utf-8")

    def commands(self):
        lines = [line for line in self.log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    def mutating_commands(self):
        result = []
        for entry in self.commands():
            cmd, args = entry["cmd"], entry["args"]
            if cmd in MUTATING and not (cmd == "timeshift" and args and args[0] == "--list"):
                result.append(entry)
            elif cmd == "gsettings" and args and args[0] == "set":
                result.append(entry)
            elif cmd == "flatpak" and args and args[0] in ("install", "uninstall", "update", "remote-add"):
                result.append(entry)
            elif cmd == "powerprofilesctl" and args and args[0] == "set":
                result.append(entry)
        return result

    @contextmanager
    def env(self, simulate=False):
        env = {
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "ZOPT_FAKE_STATE": str(self.state_path),
            "ZOPT_FAKE_LOG": str(self.log_path),
            "HOME": str(self.home),
        }
        if simulate:
            env["ZOPTIM_SIMULATE"] = "1"
        else:
            env.pop("ZOPTIM_SIMULATE", None)
        with mock.patch.dict(os.environ, env, clear=False):
            # clear=False means ZOPTIM_SIMULATE stays if it was previously set;
            # explicitly force it off instead.
            if not simulate:
                os.environ.pop("ZOPTIM_SIMULATE", None)
            yield
