# Preen

**System setup, deep cleaning and tuning for Linux.** A small GTK 3 app that
installs and removes APT/Flatpak apps, deep-cleans caches with a size preview,
manages systemd services and boot time, tunes power/swap/ZRAM, customises the
look, and backs up your settings — with a **Simulate switch** that previews
every action before anything touches your system.

> v0.3.0 (formerly "Zorin Optimizer") adds the Deep Clean page, a Services &
> Boot page and the frosted-glass theme. See [the changelog](CHANGELOG.md).

---

## Start here

| I want to… | Go to |
|---|---|
| Use the app | [User Guide](docs/USER_GUIDE.md) |
| Install it | [Quick start](#quick-start) |
| Change the code | [Architecture](docs/ARCHITECTURE.md) + [Contributing](CONTRIBUTING.md) |
| See what changed | [Changelog](CHANGELOG.md) |
| Browse all docs | [Docs index](docs/README.md) |

---

## Quick start

```bash
# 1. System dependencies
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas polkitd tar xz-utils

# 2. Build and install the .deb
cd ZorinOS-Optimizer
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
sudo apt install -y ../preen_0.3.0_all.deb

# 3. Launch
preen
```

Or run straight from a checkout:

```bash
python3 -m pip install -e .
python3 -m preen_tool.app
```

> **First time?** Launch with `preen --simulate`, turn on the Simulate switch,
> and click through the pages. The Logs page shows exactly what would have
> run — nothing is changed.

Everything is also available through `make`: run `make help`.

---

## What's inside

| Page | What it does |
|---|---|
| **Dashboard** | Welcome guide, live CPU/RAM/disk/OS stats, and a clear list of missing tools |
| **Install Apps** | 45 curated apps, search, status badges, presets, APT/Flatpak fallback, bulk actions |
| **Manage Apps** | Installed Flatpak apps + graphical APT packages; protected core packages |
| **Deep Clean** | Sized scan of APT cache, journal, thumbnails and trash — see the GB before deleting |
| **Optimize System** | Cleanup, animations, startup apps, power profile, swapfile, ZRAM — diff-based |
| **Services & Boot** | Boot-time breakdown, slowest units, start/stop/enable/disable systemd services |
| **Customize Look** | Light/dark theme, icon packs, reversible rounded-corner CSS |
| **Backup & Restore** | Timeshift snapshots, safe `~/.config` export/import |
| **Logs** | Every command, exit code and error; saveable and searchable by eye |

Header bar: **Simulate** switch and a ⋮ menu (Preferences, Help, About);
progress and errors appear in the bottom status bar.
Preferences persist to `~/.config/preen/settings.json` (0.2.x settings are
migrated automatically).

---

## Command line

```bash
preen --doctor           # installation + dependency report, no GTK
preen --doctor --json    # machine-readable
preen --check-catalog    # validate apps.json / presets.json
preen --version
preen --simulate         # start the GUI in dry-run mode
```

(`zorin-optimizer` still works as a compatibility alias for 0.2.x users.)

Missing optional tools (flatpak, timeshift, …) only disable the features that
need them; the Dashboard explains which ones.

---

## Development

```bash
make setup       # system deps + editable install
make check       # validate catalogue
make test        # 57 tests, no root / GTK / network
make doctor      # headless diagnostics
make wheel       # build a wheel (runs check + test first)
make deb         # build the Debian package
make clean       # remove generated artefacts
```

The test suite uses a fake Linux userspace (`tests/fakes.py`) and a fake GTK,
so it is safe to run anywhere. Details in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Safety

- **Simulate mode** gates every mutating action — installs, removals,
  gsettings, file deletions, icon packs, config import/export and service
  changes.
- Commands are **batched** into one polkit prompt and their exit codes are
  checked; failures appear in a dismissible banner and in Logs.
- Core system packages are locked; untrusted archives are checked for path
  traversal, links and device nodes; service names are validated before they
  ever reach `systemctl`.
- Optimisation only applies settings you actually changed, so it will not
  delete a swapfile you already had.

See [docs/ROAST.md](docs/ROAST.md) for the full list of fixes and
[docs/USER_GUIDE.md](docs/USER_GUIDE.md#6-troubleshooting) for troubleshooting.

---

## Contributing & licence

PRs are welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first. Add an app to
the catalogue? Run `make check` afterwards.

MIT — see [LICENSE](LICENSE).
