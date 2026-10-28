# Contributing to Preen

Thank you for helping. Preen targets Linux desktops with Python 3.8+ and GTK 3;
APT integration is intended for Debian and Ubuntu-family systems. Please follow
our [code of conduct](CODE_OF_CONDUCT.md).

## Get set up

On a Debian/Ubuntu-family development machine:

```bash
sudo apt install -y git python3 python3-gi gir1.2-gtk-3.0 python3-psutil

git clone https://github.com/mdadeel/Preen.git
cd Preen
make check          # validate the catalogue
make doctor         # inspect local capabilities
make test           # unittest suite; no root, display or network needed
make run            # launch the GTK app from this checkout
```

The GUI needs the system's PyGObject bindings. If your default `python3` does
not see them, use the distribution Python, for example
`make PYTHON=/usr/bin/python3 run`. Optional features also need their external
tools; see the [user guide](docs/USER_GUIDE.md#optional-tools).

For an editable Python installation, first install your distribution's venv
support (for example `sudo apt install python3-venv`), then use a virtual
environment that can see the system GTK bindings:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install -e .
preen --doctor
```

Pip may access package repositories for build dependencies. Avoid installing
into an externally managed system Python. On non-Debian distributions use the
appropriate package manager for GTK 3, PyGObject and Python; APT-specific
features still require APT/dpkg and are not universally supported.

## Project layout

See [architecture](docs/ARCHITECTURE.md) for the task queue and safety model.

| Path | Purpose |
|---|---|
| `preen_tool/app.py` | GTK-free launcher and CLI flags |
| `preen_tool/gui.py` | GTK widgets and UI logic |
| `preen_tool/cli.py` | Doctor and catalogue checks |
| `preen_tool/backend/` | Headless logic; no GTK imports |
| `preen_tool/config/` | App catalogue and presets |
| `tests/` | Unittest suite with fake Linux commands and GTK |
| `docs/` | User, architecture, audit and proposed-product documentation |

## Safety and quality rules

1. Keep the backend headless: do not import `gi` in `backend/`.
2. Never touch GTK widgets from a worker. Use `MainWindow.submit()` and update
   the UI in the main-thread callback; keep long operations off the UI thread.
3. Maintenance commands that change the system must pass `mutate=True` to
   `run_cmd`/`Report.run`; direct maintenance writes must check
   `utils.is_simulate()`. Preferences and a user-selected log save are explicit
   exceptions, so never describe Simulate as a no-write sandbox.
4. Pass untrusted values as argv, or quote them with `shlex.quote()` /
   `utils.format_cmd()` when a shell batch is unavoidable.
5. Inspect untrusted archives with `utils.safe_tar_members()` and preserve the
   destination and symlink protections; do not weaken extraction checks.
6. Add regression tests for fixes. Tests must use fakes or temporary files,
   never real `apt`, `flatpak`, `pkexec` or destructive system operations.
7. Preserve source fallback, protected-package checks, confirmations, polkit
   handling, diagnostic detail and honest failure/unknown states.

Style: PEP 8, `snake_case` functions, `CamelCase` classes, `UPPER_SNAKE_CASE`
constants and postponed annotations where applicable.

## Adding a catalogue entry

Edit `preen_tool/config/apps.json`:

```json
{"id": "myapp", "name": "My App", "flatpak": "org.example.MyApp", "apt": "myapp"}
```

- Keep `id` stable and unique. Check package names and Flatpak IDs against
  their actual repositories; runtime/SDK extensions are not applications.
- Only add an APT name that is available in the intended repositories.
- `note` is optional. Update `preen_tool/config/presets.json` if needed.
- Run `make check` and `make test`.

## Pull requests

- Work on a feature branch and explain why the change is needed.
- Include relevant check/test results, the environment and what was **not**
  tested. Fake GTK tests do not establish visual or real polkit behaviour.
- Update the changelog and user guide for user-facing changes; update privacy,
  third-party notices and package metadata when those practices change.
- Do not commit build output, caches, virtual environments or generated Debian
  artifacts. Tracked files in `debian/` are packaging sources, not build output.

## Bug and security reports

For a non-sensitive bug, include your distribution, desktop version, Preen
version or commit, reproduction steps, whether Simulate was enabled and
relevant doctor/log output. **Review and redact** usernames, paths, tokens and
other private details before posting. Saved logs contain the retained history,
not just the filtered view. See [privacy](PRIVACY.md) for more detail.

For a potential vulnerability, follow [SECURITY.md](SECURITY.md); do not post
exploits, credentials or private data in a public issue.
