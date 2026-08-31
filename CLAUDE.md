# ZorinOS Optimizer – Development Guidelines (CLAUDE.md)

## 🛠️ Build and Run Commands

### Development Run (No Install)
```bash
python3 -m zorin_optim_tool.app
```

### Build Debian Package (.deb)
```bash
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
```

### Install Debian Package
```bash
sudo apt install -y ../zorin-optimizer_0.1.0_all.deb
```

## 📐 Coding Guidelines & Style

- **Language:** Python 3.10+
- **Style Standard:** PEP 8 compliance.
- **Naming Conventions:**
  - Classes: `CamelCase` (e.g., `ZorinOptimizerApp`).
  - Functions, methods, and variables: `snake_case` (e.g., `set_power_profile`).
  - Constants: `UPPER_SNAKE_CASE` (e.g., `CONFIG_DIR`).
- **GUI Framework:** GTK 3 (via PyGObject, `gi.repository.Gtk`).
- **Asynchronous Execution:** Heavy/blocking tasks must run in daemon threads (using `threading.Thread`) and update the UI exclusively via `GLib.idle_add`.
- **System Actions / Elevation:** Use `pkexec` for root privilege commands, with `mutate=True` checks for dry-run simulation. Consolidate consecutive operations into a single command where possible to minimize Polkit prompts.
