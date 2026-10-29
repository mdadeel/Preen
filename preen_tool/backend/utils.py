"""Command execution, logging and small shared helpers.

Rules that every backend module follows:

* No implicit shell. The few commands that need one use ``bash -c`` with every
  interpolated value passed through :func:`shlex.quote`.
* Every command that changes the machine is executed with ``mutate=True`` so
  Simulate mode short-circuits it *before* anything is spawned.
* Command results are checked and reported. A failing ``apt-get`` no longer
  looks like a success.
"""
from __future__ import annotations

import inspect
import os
import shlex
import shutil
import subprocess
import threading
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

SIMULATE_ENV = "ZOPTIM_SIMULATE"
DEFAULT_TIMEOUT = 20 * 60  # package installs can legitimately take a while

_simulate_lock = threading.Lock()
_simulate = False


# ---------------------------------------------------------------------------
# Simulate mode
# ---------------------------------------------------------------------------
def set_simulate(enabled: bool) -> None:
    """Enable/disable dry-run mode for the whole process."""
    global _simulate
    with _simulate_lock:
        _simulate = bool(enabled)


def is_simulate() -> bool:
    with _simulate_lock:
        enabled = _simulate
    return enabled or os.environ.get(SIMULATE_ENV) == "1"


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def has_command(cmd: str) -> bool:
    return which(cmd) is not None


def format_cmd(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in args)


def accepts_log(func) -> bool:
    """Whether *func* can be called with a ``log=`` keyword argument."""
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == p.VAR_KEYWORD or p.name == "log" for p in params)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
class CommandResult(NamedTuple):
    """A 3-tuple (code, stdout, stderr) so existing unpacking keeps working."""

    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def simulated(self) -> bool:
        return self.out.startswith("[simulated]")

    def detail(self, limit: int = 1500) -> str:
        """Most useful chunk of output for a log line."""
        text = (self.err or "").strip() or (self.out or "").strip()
        text = text.strip()
        if len(text) > limit:
            text = "…" + text[-limit:]
        return text


@dataclass
class Outcome:
    """Returned by every mutating backend operation."""

    ok: bool
    message: str
    details: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        return self.message


def ok(message: str, *details: str) -> Outcome:
    return Outcome(True, message, [d for d in details if d])


def fail(message: str, *details: str) -> Outcome:
    return Outcome(False, message, [d for d in details if d])


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------
def run_cmd(
    args: Sequence[str],
    use_pkexec: bool = False,
    check: bool = False,
    env: Optional[dict] = None,
    timeout: Optional[int] = DEFAULT_TIMEOUT,
    mutate: bool = False,
    log=None,
    quiet: bool = False,
) -> CommandResult:
    """Run *args*, capture output, and optionally log everything.

    ``mutate=True`` declares that the command changes the system; in Simulate
    mode such commands are never spawned. ``env`` is merged into the current
    environment (the old implementation replaced it wholesale, which broke
    every command that inherited PATH/HOME/DISPLAY).
    """
    argv: List[str] = [str(a) for a in args]
    if not argv:
        return CommandResult(127, "", "[error] empty command")

    is_root = os.geteuid() == 0
    # Normalise: callers may either pass use_pkexec=True or put "pkexec" in
    # argv themselves. Exactly one pkexec, and never when already root.
    if argv[0] == "pkexec":
        argv = argv[1:]
        use_pkexec = True
    # A dry run must be able to show the command even when polkit is not
    # installed. Nothing is spawned in this branch.
    if mutate and is_simulate():
        preview = (["pkexec"] + argv) if use_pkexec and not is_root else argv
        line = "[simulate] would run: " + format_cmd(preview)
        if log and not quiet:
            log.append(line + "\n")
        return CommandResult(0, "[simulated] " + format_cmd(preview), "")

    if use_pkexec and not is_root:
        if not has_command("pkexec"):
            result = CommandResult(
                127,
                "",
                "[error] pkexec is required for this action. Install polkit "
                "(package 'polkitd' or 'policykit-1').",
            )
            if log:
                log.append("[error] " + result.err + "\n")
            return result
        argv = ["pkexec"] + argv

    full_env = os.environ.copy()
    if env:
        full_env.update({str(k): str(v) for k, v in env.items()})

    if log and not quiet:
        log.append("$ " + format_cmd(argv) + "\n")

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=full_env,
        )
    except FileNotFoundError as exc:
        result = CommandResult(127, "", "[error] command not found: {} ({})".format(argv[0], exc))
    except OSError as exc:
        result = CommandResult(126, "", "[error] cannot run {}: {}".format(argv[0], exc))
    else:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            result = CommandResult(124, out or "", (err or "") + "\n[timeout] command exceeded {}s".format(timeout))
        else:
            result = CommandResult(proc.returncode, out or "", err or "")

    if log and not quiet:
        if not result.ok:
            log.append("[failed] exit {}{}\n".format(
                result.code, ": no output" if not (result.out or result.err) else ""))
        # Preserve both complete streams for diagnostics. Outcome summaries
        # may be shortened, but the saved log must retain the original output.
        for label, stream in (("stdout", result.out), ("stderr", result.err)):
            if stream:
                log.append("[{}]\n{}{}".format(
                    label, stream, "" if stream.endswith("\n") else "\n"))

    if check and not result.ok:
        raise subprocess.CalledProcessError(result.code, argv, output=result.out, stderr=result.err)
    return result


class Report:
    """Collects the outcome of a multi-command operation."""

    def __init__(self, log=None):
        self.log = log
        self.failures: List[str] = []
        self.commands: int = 0
        self.simulated: int = 0

    def note(self, text: str) -> None:
        if self.log:
            self.log.append(text.rstrip("\n") + "\n")

    def run(self, args: Sequence[str], **kwargs) -> CommandResult:
        allow_failure = kwargs.pop("allow_failure", False)
        kwargs.setdefault("log", self.log)
        result = run_cmd(args, **kwargs)
        self.commands += 1
        if result.simulated:
            self.simulated += 1
        if not result.ok and not allow_failure:
            self.failures.append("{} → exit {} {}".format(
                format_cmd(args), result.code, result.detail(300) or "(no output)"))
        return result

    def finish(self, success: str, failure: str = "Operation failed") -> Outcome:
        if self.failures:
            message = "{} ({} of {} commands failed)".format(failure, len(self.failures), self.commands)
            return Outcome(False, message, list(self.failures))
        if self.simulated:
            return Outcome(True, "Simulation complete. No changes were made.", [])
        return Outcome(True, success, [])


def run_actions(actions, log=None) -> "Outcome":
    """Run a list of ``(label, callable, args_tuple)`` steps and aggregate.

    Used by the Optimize/Customize pages so a multi-step run reports partial
    failures instead of silently pretending everything succeeded.
    """
    outcomes: List[Outcome] = []
    for label, func, args in actions:
        if log:
            log.append("[step] {}\n".format(label))
        try:
            # Never "retry without log": a TypeError raised *inside* a
            # mutating function must not cause that function to run twice.
            result = func(*args, log=log) if accepts_log(func) else func(*args)
        except Exception as exc:
            if log:
                log.append("[error] {}: {}\n{}\n".format(label, exc, traceback.format_exc()))
            outcomes.append(fail("{}: {}".format(label, exc)))
            continue
        if isinstance(result, Outcome):
            outcomes.append(result)
        else:
            outcomes.append(fail("{} did not report an outcome".format(label)))
    if not actions:
        return ok("No changes requested. Everything already matches.")
    failed = [o for o in outcomes if not o.ok]
    if failed:
        details = ["{}: {}".format(o.message, "; ".join(o.details)) for o in failed]
        return fail("{} of {} step(s) failed".format(len(failed), len(actions)), *details)
    if is_simulate():
        return ok("Simulation complete. No changes were made.")
    return ok("Completed {} step(s).".format(len(actions)))


def elevated_script(script: str) -> List[str]:
    """Wrap a shell script in one single polkit prompt."""
    return ["pkexec", "bash", "-c", script]


def shell_join(commands: Sequence[Sequence[str]]) -> str:
    """Join argv lists into one safely quoted ``&&`` shell script."""
    return " && ".join(format_cmd(c) for c in commands)


# ---------------------------------------------------------------------------
# Desktop entry parsing
# ---------------------------------------------------------------------------
def parse_desktop_file(path: str) -> Dict[str, object]:
    """Read the fields we care about from the [Desktop Entry] group only."""
    info: Dict[str, object] = {
        "name": os.path.basename(path),
        "type": "",
        "hidden": False,
        "no_display": False,
        "autostart_enabled": None,
        "exec": "",
        "icon": "",
        "comment": "",
        "x_appimage_version": "",
    }
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            in_entry = False
            for raw in handle:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry or "=" not in line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "Name":
                    info["name"] = value or info["name"]
                elif key == "Type":
                    info["type"] = value
                elif key == "Exec":
                    info["exec"] = value
                elif key == "Icon":
                    info["icon"] = value
                elif key == "Comment":
                    info["comment"] = value
                elif key == "X-AppImage-Version":
                    info["x_appimage_version"] = value
                elif key == "Hidden":
                    info["hidden"] = value.lower() == "true"
                elif key == "NoDisplay":
                    info["no_display"] = value.lower() == "true"
                elif key == "X-GNOME-Autostart-enabled":
                    info["autostart_enabled"] = value.lower() != "false"
    except OSError:
        pass
    return info


def read_desktop_entry(path: str) -> Tuple[str, bool]:
    """Backwards-compatible (Name, Hidden) helper."""
    info = parse_desktop_file(path)
    hidden = bool(info["hidden"])
    if info["autostart_enabled"] is False:
        hidden = True
    return str(info["name"]), hidden


def set_desktop_keys(path: str, values: Dict[str, str]) -> bool:
    """Set keys inside [Desktop Entry], preserving all other groups.

    Writes atomically so an interrupted toggle cannot corrupt a .desktop file.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except OSError:
        return False
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"  # never concatenate a new key onto a truncated line

    out: List[str] = []
    in_entry = False
    seen_entry = False
    pending = dict(values)
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_entry:
                out.extend("{}={}\n".format(k, pending.pop(k)) for k in list(pending))
            in_entry = stripped == "[Desktop Entry]"
            seen_entry = seen_entry or in_entry
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if in_entry and key in values:
            if key in pending:
                out.append("{}={}\n".format(key, pending.pop(key)))
            # Drop duplicate copies of a key being changed: a later old value
            # could otherwise override the requested autostart state.
        else:
            out.append(line)
    if in_entry:
        out.extend("{}={}\n".format(k, pending.pop(k)) for k in list(pending))
    if not seen_entry:
        out.append("[Desktop Entry]\n")
        out.extend("{}={}\n".format(k, v) for k, v in pending.items())

    tmp = path + ".zoptim.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.writelines(out)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def set_autostart_hidden(path: str, hidden: bool) -> bool:
    """Disable/enable an autostart entry the way GNOME actually reads it."""
    state = "false" if hidden else "true"
    return set_desktop_keys(path, {
        "Hidden": "true" if hidden else "false",
        "X-GNOME-Autostart-enabled": state,
    })


# ---------------------------------------------------------------------------
# Tar safety (shared by icon packs and config restore)
# ---------------------------------------------------------------------------
def safe_tar_members(tar, strip_prefixes: Sequence[str] = ()) -> Tuple[List, List[str]]:
    """Return (sanitised members, rejected names).

    Rejects absolute paths, ``..`` traversal, symlinks/hardlinks and device
    nodes. Those are exactly the tricks a malicious tarball uses to write
    outside the destination directory.
    """
    allowed: List = []
    rejected: List[str] = []
    for member in tar.getmembers():
        name = member.name
        if name.startswith("/") or name.startswith("\\"):
            rejected.append(name)
            continue
        if not (member.isfile() or member.isdir()):
            rejected.append(name + " (unsupported file type)")
            continue
        relative = name
        for prefix in strip_prefixes:
            if relative == prefix.rstrip("/"):
                relative = ""
                break
            if relative.startswith(prefix):
                relative = relative[len(prefix):]
                break
        relative = relative.lstrip("/")
        parts = [p for p in relative.replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts) or (not parts and not member.isdir()):
            rejected.append(name)
            continue
        clean = "/".join(parts)
        if not clean:
            continue
        member.name = clean + ("/" if member.isdir() and not clean.endswith("/") else "")
        # Strip special bits and group/world write permission, and guarantee
        # the owner can traverse directories and read extracted files.
        member.mode = member.mode & 0o755
        member.mode |= 0o700 if member.isdir() else 0o600
        allowed.append(member)
    return allowed, rejected


def ensure_flathub(log=None, mutate: bool = True) -> bool:
    """Make sure a flathub remote exists. Tries system scope, then user scope."""
    if not has_command("flatpak"):
        if log:
            log.append("[flatpak] not installed; skipping flathub setup\n")
        return False
    result = run_cmd(["flatpak", "remotes", "--columns=name"], log=log)
    if result.ok and any(line.strip() == "flathub" for line in result.out.splitlines()):
        return True
    if not mutate or is_simulate():
        run_cmd(["flatpak", "remote-add", "--if-not-exists", "flathub",
                 "https://flathub.org/repo/flathub.flatpakrepo"],
                mutate=mutate, log=log)
        return True
    system = run_cmd(["flatpak", "remote-add", "--if-not-exists", "flathub",
                      "https://flathub.org/repo/flathub.flatpakrepo"],
                     mutate=True, log=log)
    if system.ok:
        return True
    user = run_cmd(["flatpak", "remote-add", "--if-not-exists", "--user", "flathub",
                    "https://flathub.org/repo/flathub.flatpakrepo"],
                   mutate=True, log=log)
    return user.ok
