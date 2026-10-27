# Architecture

A short map for anyone changing the code. Read
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the rules and `USER_GUIDE.md` for
user-facing behaviour.

## Module map

```
zorin-optimizer --doctor ──► cli.py ──► backend/ (headless)
           │
           └── GUI ──► app.py ──► gui.py ──┐
                                          ├──► backend/apps.py          APT / Flatpak
                                          ├──► backend/system.py        cleanup, animations, autostart
                                          ├──► backend/performance.py   power, swap, ZRAM
                                          ├──► backend/ui_customization.py  theme, icons, CSS
                                          ├──► backend/backup.py        Timeshift, ~/.config
                                          ├──► backend/dashboard.py     system info, capabilities
                                          ├──► backend/settings.py      preferences JSON
                                          └──► backend/utils.py         command runner, results, safety
```

| File | Responsibility |
|---|---|
| `app.py` | GTK-free launcher; handles `--doctor`, `--check-catalog`, `--version`, `--simulate`; friendly error when PyGObject is missing. |
| `cli.py` | Headless diagnostics, catalogue validation, JSON report. |
| `gui.py` | All GTK code, page construction, task runner, dialogs, preferences. |
| `backend/utils.py` | `run_cmd`, `CommandResult`, `Report`, `Outcome`, `run_actions`, `accepts_log`, desktop-file parsing, `safe_tar_members`, `ensure_flathub`. |
| `backend/apps.py` | Catalogue loading/validation, installed-state queries, batched install/update/uninstall. |
| `backend/settings.py` | Validated preferences in `~/.config/zorin-optimizer/settings.json`. |
| `config/*.json` | App catalogue and presets — data, not code. |

`backend/` must never import `gi`. That keeps `--doctor`, the CLI and the whole
test suite usable on a headless machine.

## Command execution

`utils.run_cmd(argv, ..., mutate=...)` is the only place subprocesses are
spawned.

- `CommandResult` is a 3-tuple `(code, out, err)` with `.ok` and `.detail()`.
- `mutate=True` declares a system change; Simulate mode short-circuits it
  **before** `Popen` and logs `[simulate] would run: ...`.
- `env=` is **merged** into `os.environ`, never replaces it.
- `use_pkexec=True` adds exactly one `pkexec` (none when already root) and
  returns a clear error if polkit is unavailable.
- `Report.run()` collects every failure into an `Outcome`; callers return that
  to the GUI, which shows a banner and logs details.
- Shell scripts are only used to batch privileged steps into one polkit
  prompt; every interpolated value goes through `shlex.quote`.

## Threading contract

```
UI thread ──submit(func, *args, done=...)──► daemon thread
                                              │ func(..., log=LogBuffer)
                                              ▼
UI thread ◄──GLib.idle_add(_finish, result, done)
```

- `MainWindow.submit()` serialises work with a lock — one operation at a time.
- Worker threads may only call `LogBuffer.append()` (which uses `idle_add`).
- All widget updates happen in `_finish` (main thread) or the `done=` callback.
- `utils.accepts_log()` inspects the signature instead of catching `TypeError`,
  so a function is never executed twice.

## Simulate contract

Every function that changes anything must:

1. pass `mutate=True` to `run_cmd`/`Report.run` for commands, **or**
2. check `utils.is_simulate()` before writing files (startup entries, CSS,
   archives), and
3. return an `Outcome` so the UI can report success/failure.

`tests/test_backend.py::test_simulate_mode_blocks_EVERY_mutating_action`
enumerates all 19 mutating operations and asserts no mutating command is
spawned and no file is written.

## Safety layers

- **Catalogue** — `validate_catalog()` checks IDs, package names and preset
  references; `--check-catalog` runs it in CI.
- **Arguments** — scanner rows are validated with strict regexes; essential
  APT packages are in `ESSENTIAL_APT_PACKAGES` and cannot be bulk-removed.
- **Archives** — `safe_tar_members()` rejects absolute paths, `..`, symlinks,
  hardlinks, device nodes and setuid bits before `extractall`.
- **Preferences** — `settings.validate()` coerces any hand-edited JSON back to
  safe values.
- **Diff-based optimisation** — only settings that changed from the detected
  baseline are applied.

## Testing

`tests/fakes.py` creates fake `flatpak`, `dpkg`, `dpkg-query`, `gsettings`,
`pkexec`, `swapon`, `powerprofilesctl` and `timeshift` binaries that log every
invocation to JSONL. Tests assert on those logs, not on the host system.

- `test_backend.py` — backend behaviour, catalogue, packaging, tar safety,
  simulate mode, CLI.
- `test_settings.py` — preference persistence and validation.
- `test_gui_smoke.py` — import surface and GTK-free launcher error path.
- `test_gui_runtime.py` — a fake GTK that builds all 7 pages and fires every
  handler.

Run with `make test` / `python3 -m unittest discover -s tests -v`. No root,
no display server, no network.

## Packaging

- `pyproject.toml` uses **automatic package discovery** so `backend/` and
  `config/*.json` are always shipped. `MANIFEST.in` covers the sdist.
- `debian/` builds the `.deb` via `pybuild`; `debian/rules` skips the test
  suite inside the build chroot.
- `.gitignore` excludes `build/`, `.pybuild/`, `*.egg-info`, `.venv`,
  `__pycache__` and generated `debian/zorin-optimizer/`.
- `test_built_wheel_contains_the_backend` builds a real wheel and asserts the
  required files are present — this is the regression test for the v0.1.0
  packaging failure.
