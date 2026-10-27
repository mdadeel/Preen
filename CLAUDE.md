# ZorinOS Optimizer – Development Guidelines (CLAUDE.md)

## 🛠️ Commands

The `Makefile` is the single source of truth — run `make help`. Most used:

```bash
make setup       # system deps + editable install (needs sudo)
make run         # python3 -m preen_tool.app
make simulate    # same, in dry-run mode
make doctor      # headless installation/dependency report
make check       # validate apps.json / presets.json
make test        # python3 -m unittest discover -s tests -v
make lint        # python3 -m compileall -q preen_tool tests
make wheel       # check + test + build wheel
make deb         # check + test + dpkg-buildpackage
make clean       # remove generated artefacts
```

All CLI flags work without GTK/display:

```bash
python3 -m preen_tool.app --doctor [--json]
python3 -m preen_tool.app --check-catalog
python3 -m preen_tool.app --version
python3 -m preen_tool.app --simulate
```

## 📐 Style

- Python 3.8+, PEP 8. `CamelCase` classes, `snake_case` functions/variables,
  `UPPER_SNAKE_CASE` constants, `from __future__ import annotations`.
- `.editorconfig` defines indentation (4 spaces for Python, 2 for JSON/YAML/MD,
  tabs for `Makefile` and `debian/rules`).

## 🧱 Layout

- `app.py` — GTK-free launcher and CLI flags.
- `gui.py` — **all** GTK code: pages, task runner, dialogs, preferences.
- `cli.py` — `--doctor`, `--check-catalog`.
- `backend/` — headless, never imports `gi`:
  `utils` (runner/results/safety), `apps` (catalogue + package ops),
  `system`, `performance`, `ui_customization`, `backup`, `dashboard`,
  `settings` (validated preferences JSON).
- `config/` — `apps.json` (catalogue), `presets.json`.
- `docs/` — `USER_GUIDE.md`, `ARCHITECTURE.md`, `ROAST.md`, `README.md`
  (index), `archive/` (historical documents).
- `tests/` — unittest suite with `fakes.py` (fake Linux userspace + fake GTK).

## 🔒 Rules

1. **Asynchronous execution:** heavy work runs in daemon threads submitted via
   `MainWindow.submit()`. Never touch a widget from a worker thread — use
   `GLib.idle_add` or the `done=` callback (already on the UI thread). Tasks
   are serialised; do not spawn ad-hoc threads.
2. **System actions / elevation:** use `run_cmd(..., use_pkexec=True,
   mutate=True)` or `Report.run(...)`. **Every** command that changes the
   machine must set `mutate=True`, otherwise Simulate mode will not protect it.
   Commands that write files directly must check `utils.is_simulate()` first.
   Batch consecutive privileged steps into one `pkexec bash -c` script using
   `shlex.quote`/`format_cmd` to minimise polkit prompts.
3. **Results:** mutating backend functions return `Outcome` (`ok()`/`fail()`).
   Check `CommandResult.ok`; never discard stderr. Show failures in the
   non-modal banner, not a stack of modals.
4. **Untrusted archives:** pass tar members through
   `utils.safe_tar_members()` before `extractall`.
5. **Catalogue:** every app needs a real `flatpak` ID or `apt` package; run
   `make check` after editing `config/*.json`. Presets reference app `id`s,
   not Flatpak IDs.
6. **Preferences:** new settings go in `backend/settings.py` with a validated
   default, and should be exposed in the Preferences dialog + user guide.
7. **Tests:** add a regression test in `tests/` for every bug fix. Use
   `tests/fakes.py`; never call real apt/flatpak/pkexec in tests. Update the
   fake GTK when adding new widgets or enum constants.
8. **Docs:** user-facing changes update `docs/USER_GUIDE.md` and
   `CHANGELOG.md`; architecture changes update `docs/ARCHITECTURE.md`.
