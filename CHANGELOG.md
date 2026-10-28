# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

A GNOME-native dark GTK 3 refresh of all nine pages, retaining the existing
backend, package catalogue and serial task queue.

### Added

- Shared dark design tokens, grouped searchable sidebar, responsive cards and
  button rows, compact simulation control and contextual notices.
- Honest package and cleanup states, partial-scan warnings, protected rows,
  severity-coloured selectable logs, and explicit unavailable metrics.
- Regression coverage for snapshot refresh, simulation, queue callbacks,
  diagnostics, cleanup measurements and package/service scan failures.
- Bundled Preen launcher artwork, checkbox/radio indicators and offline
  catalogue marks with generic fallbacks, plus a proposed roadmap for the
  visual refresh, folder organizer and future Linux utilities.
- Two example screenshots, a desktop privacy policy, security reporting
  guidance, third-party notices, community conduct and a proposed minimal,
  no-gradient website plan.

### Changed

- Dashboard summaries and cleanup totals describe measured data and estimates;
  journal usage above its 100 MiB target is only an upper bound.
- Command logs retain stdout, stderr and exit codes. Simulated privileged
  commands can be previewed without polkit and report that no changes occurred.
- Cleanup, uninstall and restore always require confirmation; the preference
  controls the additional confirmation for Update All.
- README and user guidance now distinguish source from release assets, explain
  Simulate and package-protection limits, and advise redacting sensitive logs.
- Source archives and native package staging include the policy, license,
  third-party notices and screenshot documentation; Python metadata links to
  the project documentation and policies.

### Fixed

- Light, dark and Follow system appearance now affect Preen only and persist
  across restarts, without writing the GNOME colour scheme or GTK theme.
  Explicit choices are not overwritten by desktop changes; simulation previews
  without saving. Desktop-wide scaling, icon packs and GTK corner settings are
  separated and confirmed before applying.
- Primary actions, status text, selected segments and control icons have more
  legible dark/light contrast. Installed desktop icons are resolved before
  offline marks and generic fallbacks; preferences saves preserve appearance.
- The packaged launcher ID matches the GTK application ID for desktop shell
  icon association; the old desktop ID remains as a hidden compatibility alias.
- The package-source selector no longer recursively emits GTK toggle signals
  and crash when switching Flatpak / APT. A failed Flathub setup no longer
  silently skips an unrelated APT batch.
- Timeshift lists parse the actual `>` marker and empty descriptions; an
  explicit Refresh List can request polkit while startup never prompts.
  Failed reads are not shown as empty, and manual snapshots use the on-demand tag.
- Config restore inspects archives off the UI thread and refuses existing
  destination symlinks; descriptor-based extraction protects older Python
  versions too. Existing icon themes are backed up instead of deleted.
- Existing inactive swapfiles and custom ZRAM configurations are not
  reformatted or removed. Trash cleanup removes matching metadata safely.
- Failed systemd rows and multi-part boot durations are parsed correctly;
  queued log filtering, clearing and appends no longer duplicate entries.
  Startup-app scans run in the worker, duplicate desktop keys are corrected,
  and multi-step exceptions retain tracebacks.
- Backup snapshot refresh no longer references an out-of-scope `page`; export
  and import controls are constructed with the Backup page.
- Journal vacuum failures now reach the GUI and log instead of reporting success.
- Failed package and service scans no longer masquerade as empty results;
  unavailable power profiles no longer appear as a balanced setting.
- Callback errors retain tracebacks and their banner is not replaced by a
  later success notice. Busy/health and notice widgets are actually revealed.
- A symlink used as a cleanup root is refused instead of traversed.

## [0.4.0] - 2026-10-27

A macOS-inspired design pass, a queue-based task runner that no longer drops
background work, and a round of feature upgrades across every page.

### Added

- **Task queue**: background reads and actions now queue in FIFO order
  instead of being rejected while another task runs. Startup reads (boot
  info, service list, cleanable scan, Timeshift snapshots and preferences)
  all complete reliably.
- **Dashboard**: swap usage card with its own accent colour, plus load
  average in the system summary line.
- **Deep Clean**: pip cache is now a cleanable item, alongside select-all /
  clear buttons and a live counter showing how many items are ticked and how
  much space they reclaim.
- **Services**: Restart action, a "Running only" filter, a visible
  result count, and correct status colours (green running, red failed,
  grey stopped).
- **Customize Look**: desktop text scaling factor with four presets, applied
  through gsettings and gated by Simulate mode like every other change.
- **Optimize System**: swapfile size is now selectable (1, 2, 4 or 8 GB)
  instead of a fixed 2 GB.
- **Backup & Restore**: read-only Timeshift snapshot list with a refresh
  button.
- **Logs**: filter entry that shows only matching lines while keeping the
  full history in memory.
- **Install Apps**: catalogue grows from 45 to 55 curated apps across 10
  categories, with a new "Flatpak Toolkit" preset (Flatseal, Extension
  Manager, Mission Center, Warehouse and more).
- **Preferences**: choose which page opens on startup.

### Changed

- macOS-style visual refresh: grouped sidebar sections with small caps
  headers, a segmented source switch replacing the dropdown, softer frosted
  cards, an SF-like font stack, rounded 16 px surfaces and refined pill
  buttons.
- Service actions now report correct grammar ("started", "stopped",
  "restarted") instead of malformed strings.
- User-facing strings no longer use em dashes.
- About dialog and Debian packaging point at the current Preen repository.

### Fixed

- Queued `submit()` calls were silently rejected while a task was running,
  which left several pages unpopulated at startup.
- Manage Apps empty state did not explain a search with no matches.
- Snapshot and other startup refreshes now survive being enqueued together.

## [0.3.0] - 2026-10-28

Rebrand to **Preen**, system setup, deep cleaning and tuning for Linux
(formerly "Zorin Optimizer"), plus two new feature pages and a visual pass.

### Added

- **Deep Clean page**: sized scan of the APT cache, systemd journal,
  thumbnail cache and trash; every item shows how much space it reclaims
  *before* anything is deleted. Cleaning is gated by Simulate mode and batched
  into one polkit prompt for root items.
- **Services & Boot page**: boot-time breakdown via `systemd-analyze`, the
  slowest units, and a searchable systemd service list with
  start/stop/enable/disable (unit names are validated before they reach
  `systemctl`).
- Frosted-glass theme: translucent cards, sidebar and footer over a soft
  window gradient; follows the system light/dark theme.

### Changed

- Renamed: Python module `zorin_optim_tool` → `preen_tool`, executable/script
  `preen` (the old `zorin-optimizer` command still works as an alias),
  `.deb` package `preen`, desktop entry `preen.desktop`.
- Preferences moved to `~/.config/preen/settings.json`; 0.2.x settings are
  migrated automatically on first launch.
- 9-page sidebar with colored System-Settings-style tiles; header bar is now
  flat and compact with Preferences/Help/About under one ⋮ menu; progress and
  errors moved to a bottom status bar.

### Fixed

- The GUI crashed on startup on systems shipping Gdk 4.0, `Gdk` is now
  pinned to 3.0 before import.

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
- `.gitignore`, build output, `.pyc`, egg-info and virtualenvs are no longer
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
