# ZorinOS Optimizer – Development Guidelines (CLAUDE.md)

## 🛠️ Build and Run Commands

### Development run (no install)
```bash
python3 -m zorin_optim_tool.app
python3 -m zorin_optim_tool.app --simulate   # dry-run from startup
```

### Headless diagnostics (no GTK/display required)
```bash
python3 -m zorin_optim_tool.app --doctor
python3 -m zorin_optim_tool.app --check-catalog
```

### Tests
```bash
python3 -m unittest discover -s tests -v      # or: pytest -q
```

### Build Debian package (.deb)
```bash
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
sudo apt install -y ../zorin-optimizer_0.2.0_all.deb
```

## 📐 Coding Guidelines & Style

- **Language:** Python 3.8+ (PEP 8). Classes `CamelCase`, functions and
  variables `snake_case`, constants `UPPER_SNAKE_CASE`.
- **Layout:** `zorin_optim_tool/app.py` is the GTK-free launcher;
  `gui.py` holds all GTK code; `backend/` is headless and importable without
  PyGObject; `cli.py` holds `--doctor` / `--check-catalog`.
- **GUI framework:** GTK 3 via PyGObject (`gi.repository.Gtk`).
- **Asynchronous execution:** heavy work runs in daemon threads submitted
  through `MainWindow.submit()`. **Never touch a widget from a worker thread** —
  use `GLib.idle_add` (or the `done=` callback, which already runs on the UI
  thread). Tasks are serialised; do not spawn ad-hoc threads.
- **System actions / elevation:** use `run_cmd(..., use_pkexec=True,
  mutate=True)` or `Report.run(...)`. Every command that changes the machine
  **must** set `mutate=True`, otherwise Simulate mode will not protect it.
  Batch consecutive privileged operations into one `pkexec bash -c` script
  using `shlex.quote`/`format_cmd` to minimise polkit prompts.
- **Results:** mutating backend functions return `Outcome` (`ok()`/`fail()`);
  check command exit codes with `CommandResult.ok` and never discard stderr.
- **Untrusted archives:** always pass tar members through
  `utils.safe_tar_members()` before `extractall`.
- **Catalogue:** every app needs a real `flatpak` ID or `apt` package; run
  `--check-catalog` after editing `config/*.json`. Presets must reference
  catalogue `id` values, not Flatpak IDs.
- **Tests:** add a regression test in `tests/` for every bug fix. Use the fake
  userspace in `tests/fakes.py`; never call real apt/flatpak/pkexec in tests.
