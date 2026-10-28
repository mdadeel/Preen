# Architecture

A short map for anyone changing the code. Read
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the workflow and `USER_GUIDE.md`
for user-facing behaviour.

## Module map

```
preen --doctor ──► cli.py ──► backend/ (headless)
      │
      └── GUI ──► app.py ──► gui.py ──┐
                                      ├──► backend/apps.py             APT / Flatpak
                                      ├──► backend/system.py           cleanup, animations, autostart
                                      ├──► backend/performance.py      power, swap, ZRAM
                                      ├──► backend/ui_customization.py  theme, scaling, icons, CSS
                                      ├──► backend/backup.py           Timeshift, ~/.config archives
                                      ├──► backend/dashboard.py        metrics, capabilities
                                      ├──► backend/deepclean.py        sized scans and cleaning
                                      ├──► backend/services.py         systemd units and boot analysis
                                      ├──► backend/settings.py         preferences JSON
                                      └──► backend/utils.py            runner, outcomes, safety helpers
```

| File | Responsibility |
|---|---|
| `app.py` | GTK-free launcher. Handles `--doctor`, `--check-catalog`, `--version`, `--simulate` and prints a friendly error when PyGObject is missing. |
| `cli.py` | Headless diagnostics, catalogue validation and the JSON report. |
| `gui.py` | Nine GTK 3 screens, light/dark design tokens, dialogs, preferences, diagnostic log and the serial task queue. |
| `backend/utils.py` | `run_cmd`, `CommandResult`, `Report`, `Outcome`, `run_actions`, desktop-file parsing, `safe_tar_members`, `ensure_flathub`. |
| `backend/apps.py` | Catalogue loading and validation, two-query installed-state detection, batched install/update/uninstall. |
| `backend/deepclean.py` | Reclaimable-space scans, size formatting and simulate-gated cleaning. |
| `backend/services.py` | systemd listing and actions, boot analysis, strict unit-name validation. |
| `backend/settings.py` | Validated preferences in `~/.config/preen/settings.json` with legacy migration. |
| `config/*.json` | The app catalogue and presets. These are data, not code. |

`backend/` must never import `gi`. That keeps `--doctor`, the CLI and the
whole test suite usable on a headless machine.

## Command execution

Managed blocking commands use `utils.run_cmd(argv, ..., mutate=...)`.
Opening the separate Timeshift GUI is intentionally non-blocking.

- `CommandResult` is a named tuple `(code, out, err)` with `.ok`,
  `.simulated` and `.detail()`.
- `mutate=True` declares a system change. Simulate mode short-circuits it
  before `Popen` and logs `[simulate] would run: ...`.
- `env=` is merged into `os.environ`, never replaced.
- `use_pkexec=True` adds exactly one `pkexec` (none when already root) and
  returns a clear error when polkit is unavailable. Simulated commands are
  previewed before checking for polkit and do not launch a process.
- `Report.run()` collects failures into an `Outcome`; the GUI shows a banner
  and the log retains command stdout, stderr and exit codes (up to the
  4,000-line in-memory retention limit).
- Shell scripts only exist to batch privileged steps into one polkit
  prompt, and every interpolated value passes through `shlex.quote`.

## Threading and the task queue

```
UI thread ──submit(func, *args, done=...)──► FIFO queue
                                                │ one task at a time
                                                ▼
                                          daemon thread
                                                │ func(..., log=LogBuffer)
UI thread ◄──────── GLib.idle_add(_finish) ─────┘
```

- `MainWindow.submit()` enqueues work. `_pump_queue()` starts the next task
  only when the previous one finished, so callers may enqueue several reads
  at once without losing any.
- Worker threads may only call `LogBuffer.append()`, which itself uses
  `GLib.idle_add`.
- All widget updates happen in `_finish` on the main thread or inside a
  `done=` callback. Busy state remains active through callbacks and queued
  refreshes; the Simulate switch and action buttons cannot change mid-batch.
- `utils.accepts_log()` inspects signatures instead of catching
  `TypeError`, so a function is never executed twice. Archive inspection and
  startup-app scans also use the queue.
- Look and optimization settings have separate refresh paths. A Gio settings
  monitor queues appearance reads after external GNOME changes without
  discarding a staged theme choice. Log rendering coalesces pending updates
  and uses sequence numbers so filter/clear races do not duplicate lines.

## Simulate contract

Every function that changes anything must:

1. pass `mutate=True` to `run_cmd` or `Report.run` for commands, or
2. check `utils.is_simulate()` before writing files (startup entries, CSS,
   archives, icon packs), and
3. return an `Outcome` so the UI can report success or failure.

`tests/test_backend.py::test_simulate_mode_blocks_EVERY_mutating_action`
enumerates every mutating operation and asserts no command is spawned and no
file is written in Simulate mode.

## Safety layers

- **Catalogue.** `validate_catalog()` checks IDs, package names and preset
  references. `preen --check-catalog` runs it locally and in packaging.
- **Arguments.** Scanner rows pass strict regular expressions before they
  become command arguments, and essential APT packages live in
  `ESSENTIAL_APT_PACKAGES`.
- **Archives.** `safe_tar_members()` rejects absolute paths, `..`
  traversal, symlinks, hardlinks, device nodes and unsafe permissions.
  Config restore also refuses destination symlinks and uses directory-relative,
  no-follow file descriptors and atomic file replacement, including on older
  Python versions without `tarfile` extraction filters. Replaced icon themes
  are kept in a backup directory.
- **Preferences.** `settings.validate()` coerces hand-edited JSON back to
  known-safe values.
- **Diff-based optimisation.** Only settings that changed from the detected
  baseline are applied. Existing inactive swapfiles and custom or edited ZRAM
  configurations are not overwritten or removed.
- **Cleanable paths.** Only allowlisted directories are emptied; a symlink
  used as a cleanable root is refused. Unknown scan sizes stay unknown.
  Journal size above its retention target is an upper bound, not a promise.
- **Atomic writes.** Preferences, desktop entries and CSS go through a temp
  file and `os.replace`.

## Testing

`tests/fakes.py` creates fake `flatpak`, `dpkg`, `dpkg-query`, `gsettings`,
`pkexec`, `swapon`, `powerprofilesctl` and `timeshift` binaries that log
every invocation to JSONL. Fake `gsettings` persists changes and can emulate
older schemas and failures. A second fake GTK walks every screen and
exercises handlers without a display server.

- `test_backend.py` covers backend behaviour, packaging, tar safety,
  Simulate mode and the CLI; `test_theme.py` covers stateful modern and legacy
  GNOME appearance changes, failures and simulation.
- `test_deepclean.py`, `test_services.py`, `test_settings.py` cover the
  matching modules.
- `test_gui_smoke.py` checks the import surface and the GTK-missing error
  path.
- `test_gui_runtime.py` builds all nine pages and exercises handlers, the
  snapshot callback, queued work, simulation, notices, filters and counters.

The fake GTK tests do not establish visual correctness or replace tests on a
real GNOME desktop with polkit and package managers.

Run them with `make test` or
`python3 -m unittest discover -s tests -v`. No root, display server or
network is required.

## Packaging

- `pyproject.toml` uses automatic package discovery so `backend/` and
  `config/*.json` always ship. `MANIFEST.in` covers the source archive.
- `packaging/build_deb.sh` stages a Debian package without debhelper.
- `packaging/build_appimage.sh` builds a small AppImage that reuses the
  system Python and GTK.
- `.gitignore` excludes `build/`, `dist/`, `*.egg-info`, virtual
  environments, bytecode caches and generated Debian artefacts.
