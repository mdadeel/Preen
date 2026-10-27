# Contributing

Thanks for helping out. This project targets Zorin OS 17/18 (Ubuntu 22.04/24.04
base) with GTK 3 and Python 3.8+.

## 1. Get set up

```bash
git clone https://github.com/mdadeel/ZorinOS-Optimizer.git
cd ZorinOS-Optimizer
make setup          # installs the system GTK/psutil packages (needs sudo)
make check          # catalogue + doctor, no GTK required
make test           # full regression suite, no GTK/root/network required
make run            # launch the GTK app
```

Prefer the `Makefile` targets over memorising commands — `make help` lists all
of them. If you cannot run `make setup` (non-Debian host), the equivalent is:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-psutil flatpak \
                 gsettings-desktop-schemas polkitd tar xz-utils
python3 -m pip install -e .
```

## 2. Project layout

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The short version:

| Path | Purpose |
|---|---|
| `zorin_optim_tool/app.py` | GTK-free launcher and CLI flags |
| `zorin_optim_tool/gui.py` | all GTK widgets and UI logic |
| `zorin_optim_tool/cli.py` | `--doctor`, `--check-catalog` |
| `zorin_optim_tool/backend/` | headless logic, no GTK imports |
| `zorin_optim_tool/config/` | `apps.json` catalogue and `presets.json` |
| `tests/` | unittest suite with a fake Linux userspace |

## 3. Rules that must not be broken

1. **Backend must stay headless.** Never import `gi` in `backend/`; it must be
   importable over SSH and in CI.
2. **Never touch a GTK widget from a worker thread.** Submit work with
   `MainWindow.submit()` and update the UI in the `done=` callback, which runs
   on the main thread.
3. **Every mutating command must pass `mutate=True`.** Otherwise Simulate mode
   will not protect it. Use `Report.run()` so exit codes are checked.
4. **Never interpolate untrusted values into a shell string** without
   `shlex.quote()` / `utils.format_cmd()`. Prefer argv lists.
5. **Untrusted archives** go through `utils.safe_tar_members()` before
   `extractall()`.
6. **Add a test for every bug fix.** Use `tests/fakes.py`; tests must never
   call real `apt`, `flatpak` or `pkexec`.

Style: PEP 8, `snake_case` functions, `CamelCase` classes, `UPPER_SNAKE_CASE`
constants, `from __future__ import annotations` at the top of modules.

## 4. Adding an app to the catalogue

Edit `zorin_optim_tool/config/apps.json`:

```json
{"id": "myapp", "name": "My App", "flatpak": "org.example.MyApp", "apt": "myapp"}
```

- `id` is used by presets — keep it stable and unique.
- Verify the Flatpak ID really exists on Flathub (its build repo is usually
  `github.com/flathub/<app-id>`). Runtime/SDK extensions are **not** apps.
- Only add an `apt` name that exists in the Ubuntu/Zorin repositories.
- `note` is optional and appears as a tooltip in the UI.
- If you add an app to a preset, update `config/presets.json` too.

Then run:

```bash
make check            # validates IDs, package names and preset references
make test
```

## 5. Pull requests

- Work on a feature branch; never push directly to `main`.
- Keep the diff focused and explain *why*, not just *what*.
- Include the output of `make check` and `make test`.
- Do not commit build output, `.pyc`, `.venv`, `*.egg-info` or generated
  `debian/` trees — they are covered by `.gitignore`.
- New user-facing behaviour needs a line in `CHANGELOG.md` and, if it changes
  a workflow, an update to `docs/USER_GUIDE.md`.

## 6. Reporting bugs

Include the output of `zorin-optimizer --doctor`, the relevant **Logs** page
contents (Logs → Save Log…), your Zorin OS version, and whether Simulate mode
was on.
