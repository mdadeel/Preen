# Preen Development Guidelines

## Commands

The `Makefile` is the single source of truth. Run `make help` to list every
target. The most used ones:

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

All CLI flags work without GTK or a display:

```bash
python3 -m preen_tool.app --doctor [--json]
python3 -m preen_tool.app --check-catalog
python3 -m preen_tool.app --version
python3 -m preen_tool.app --simulate
```

## Style

- Python 3.8+, PEP 8. `CamelCase` classes, `snake_case` functions and
  variables, `UPPER_SNAKE_CASE` constants, and
  `from __future__ import annotations` at the top of modules.
- User-facing text avoids em dashes. Use commas, colons or plain hyphens.
- `.editorconfig` defines indentation: 4 spaces for Python, 2 for JSON/YAML
  and Markdown, tabs for the `Makefile` and `debian/rules`.

## Layout

- `app.py`: GTK-free launcher and CLI flags.
- `gui.py`: all GTK code, including pages, the stylesheet, the task queue,
  dialogs and preferences.
- `cli.py`: `--doctor`, `--check-catalog` and the JSON report.
- `backend/`: headless logic, never imports `gi`. Modules: `utils` (runner,
  results, safety), `apps` (catalogue and package operations), `system`,
  `performance`, `ui_customization`, `backup`, `dashboard`, `deepclean`,
  `services`, `settings` (validated preferences JSON).
- `config/`: `apps.json` catalogue and `presets.json`.
- `docs/`: user and architecture guides, release instructions, functional
  review, product roadmap and website plan; see the `README.md` index.
- `tests/`: unittest suite with `fakes.py`, a fake Linux userspace and a
  fake GTK.

## Rules

1. **Asynchronous execution.** Heavy work runs in daemon threads enqueued
   through `MainWindow.submit()`, which serialises tasks in a FIFO queue.
   Never touch a widget from a worker thread. Use `GLib.idle_add` or the
   `done=` callback, which already runs on the UI thread. Do not spawn
   ad-hoc threads.
2. **System actions and elevation.** Use `run_cmd(..., use_pkexec=True,
   mutate=True)` or `Report.run(...)`. Every command that changes the
   machine must set `mutate=True`, otherwise Simulate mode will not protect
   it. Commands that write files directly must check
   `utils.is_simulate()` first. Batch consecutive privileged steps into one
   `pkexec bash -c` script using `shlex.quote` or `format_cmd` to keep
   polkit prompts to a minimum.
3. **Results.** Mutating backend functions return an `Outcome` from
   `ok()` or `fail()`. Check `CommandResult.ok` and never discard stderr.
   Show failures in the non-modal banner, not a stack of modal dialogs.
4. **Untrusted archives.** Pass tar members through
   `utils.safe_tar_members()` before `extractall`.
5. **Catalogue.** Every app needs a real Flatpak ID or APT package name.
   Run `make check` after editing `config/*.json`. Presets reference app
   `id` values, not Flatpak IDs.
6. **Preferences.** New settings go in `backend/settings.py` with a
   validated default, and must be exposed in the Preferences dialog and the
   user guide.
7. **Tests.** Add a regression test in `tests/` for every bug fix. Use
   `tests/fakes.py`; never call real apt, flatpak or pkexec in tests.
   Extend the fake GTK when adding new widgets or enum constants.
8. **Docs.** User-facing changes update `docs/USER_GUIDE.md` and
   `CHANGELOG.md`. Architecture changes update `docs/ARCHITECTURE.md`.
