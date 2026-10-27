# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-27

Reliability rewrite plus a UX and repository clean-up pass. The full audit of
the previous release is in [`docs/ROAST.md`](docs/ROAST.md).

### Fixed

- The wheel/`.deb` now ships `preen_tool/backend/`; the installed app
  previously crashed with `ModuleNotFoundError` on startup.
- Simulate mode now gates **all** mutating actions (themes, gsettings, icon
  packs, CSS, config export/import, Timeshift, power profiles, startup apps),
  not just APT/Flatpak commands.
- Both Timeshift buttons crashed on click (`__import__(...).backup...`).
- The async runner re-executed mutating functions after an internal
  `TypeError`; it now inspects signatures and runs each function once.
- GTK widgets were updated from worker threads; all updates now use
  `GLib.idle_add` and a serialised task runner.
- Command exit codes and stderr were ignored; failures are now aggregated into
  an `Outcome` and shown in the UI.
- `"installed" in "purge ok not-installed"` reported purged packages as
  installed; status parsing is now exact and multiarch-aware.
- Installed-state detection used ~60 subprocesses on the UI thread; it now
  uses two cached queries.
- "Run Optimization" deleted `/swapfile` and disabled ZRAM unconditionally;
  it is now diff-based and only applies changed settings.
- ZRAM used the invalid `systemctl start /dev/zram0` unit.
- Tar path-traversal / symlink holes in config import and icon-pack install.
- Startup toggles wrote `Hidden` outside `[Desktop Entry]` and ignored
  `X-GNOME-Autostart-enabled`.
- `run_cmd(env=...)` replaced the whole environment instead of merging it.
- Five un-installable Flatpak IDs (SDK/Vulkan-layer extensions and three
  nonexistent repos) were replaced with real apps.

### Added

- `zorin-optimizer --doctor`, `--doctor --json`, `--check-catalog`,
  `--version`, `--simulate`.
- Catalogue validation, APT alternatives for 20+ apps, and `note` tooltips.
- Persistent Preferences (default source, start in Simulate, confirmations,
  dependency warnings, dashboard auto-refresh).
- Dashboard landing page with a getting-started guide, system stats and a
  tool-availability panel with plain-language warnings.
- Non-modal notification banner, progress spinner, persistent Simulate banner,
  empty states, selection counters, search filters, Select all / Clear,
  Help and About dialogs, primary/destructive button styling.
- `LICENSE`, `CONTRIBUTING.md`, this changelog, `Makefile`, `.editorconfig`,
  `docs/USER_GUIDE.md`, `docs/ARCHITECTURE.md`, `docs/README.md` and
  `docs/archive/` for historical documents.
- 36 regression tests with a fake Linux userspace and a fake GTK;
  `docs/ci-workflow.yml.example` for GitHub Actions.
- `.gitignore` — build output, `.pyc`, egg-info and virtualenvs are no longer
  committed.

### Changed

- GUI split into `gui.py` (GTK) and a GTK-free `app.py` launcher.
- Operations are batched into one `pkexec` prompt; essential APT packages are
  protected from bulk uninstall; scanner rows are validated.
- Dashboard reads `/etc/os-release` and works without psutil.
- Version bumped to 0.2.0; Debian metadata updated.

## [0.1.0] - 2025-10-26

- Initial MVP: GTK 3 sidebar UI, APT/Flatpak installer, cleanup, power
  profiles, swap/ZRAM, theme/customisation, Timeshift and config backup,
  dashboard and log view.
