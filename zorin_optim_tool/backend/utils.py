import os
import shlex
import shutil
import subprocess
from typing import List, Optional, Tuple

# Global simulate flag
_SIMULATE = False


def set_simulate(enabled: bool):
    global _SIMULATE
    _SIMULATE = enabled


def is_simulate() -> bool:
    return _SIMULATE or os.environ.get("ZOPTIM_SIMULATE") == "1"


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def has_command(cmd: str) -> bool:
    return which(cmd) is not None


def run_cmd(args: List[str], use_pkexec: bool = False, check: bool = False, env: Optional[dict] = None,
            timeout: Optional[int] = None, mutate: bool = False) -> Tuple[int, str, str]:
    """Run a command and capture output.
    - If use_pkexec is True, run via pkexec for privilege escalation.
    - If mutate is True and simulate mode is on, do not execute and return success.
    """
    import os
    is_root = (os.geteuid() == 0)
    if use_pkexec:
        if not is_root:
            if not has_command("pkexec"):
                raise RuntimeError("pkexec is required for elevated operations. Please install polkit.")
            args = ["pkexec"] + args
    if len(args) > 0 and args[0] == "pkexec" and is_root:
        args = args[1:]
    if mutate and is_simulate():
        # Simulate successful execution
        return 0, "[simulated] " + " ".join(shlex.quote(a) for a in args), ""
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    except FileNotFoundError as e:
        return 127, "", f"[error] command not found: {args[0]} ({e})"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return proc.returncode or 124, out, err + "\n[timeout]"
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output=out, stderr=err)
    return proc.returncode, out, err


def ensure_flathub() -> bool:
    """Ensure flathub is configured. Returns True if available/already configured."""
    if not has_command("flatpak"):
        return False
    code, out, _ = run_cmd(["flatpak", "remotes", "--columns=name"])  # list remotes
    if code != 0:
        return False
    if any(line.strip() == "flathub" for line in out.splitlines()):
        return True
    code, _, _ = run_cmd(["flatpak", "remote-add", "--if-not-exists", "flathub", "https://flathub.org/repo/flathub.flatpakrepo"],
                         use_pkexec=False, mutate=True)
    return code == 0


def read_desktop_entry(path: str):
    """Return (Name, Hidden) from a .desktop file (Hidden means disabled in autostart)."""
    name = os.path.basename(path)
    hidden = False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("Name="):
                    name = line.split("=", 1)[1].strip()
                elif line.startswith("Hidden="):
                    hidden = line.split("=", 1)[1].strip().lower() == "true"
    except Exception:
        pass
    return name, hidden


def set_autostart_hidden(path: str, hidden: bool) -> bool:
    try:
        lines = []
        found = False
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("Hidden="):
                    lines.append(f"Hidden={'true' if hidden else 'false'}\n")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"Hidden={'true' if hidden else 'false'}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False
