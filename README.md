# Preen

**System setup, deep cleaning and tuning for Linux, in one calm window.**

Preen is a small GTK 3 desktop app that installs and removes APT and Flatpak
apps, reclaims disk space with an honest size preview, manages systemd
services and boot time, tunes power, swap and ZRAM, customises the look of
your desktop, and backs up your settings. Every action is protected by a
**Simulate switch** that previews the exact commands first, so nothing
changes until you say so.

- Native Python 3 and GTK 3, no daemon, no telemetry
- One polkit prompt per batch instead of one password prompt per package
- Core desktop packages are locked so a cleanup cannot break your session
- Works on Ubuntu, Zorin OS, Debian, Pop!_OS, Linux Mint and similar systems

---

## Table of contents

1. [About Preen](#about-preen)
2. [Features at a glance](#features-at-a-glance)
3. [Installation](#installation)
4. [First five minutes](#first-five-minutes)
5. [Command line](#command-line)
6. [Development](#development)
7. [Safety model](#safety-model)
8. [Project layout](#project-layout)
9. [Contributing and licence](#contributing-and-licence)

---

## About Preen

Linux desktops ship with dozens of small maintenance tasks scattered across
the terminal: removing old packages, vacuuming logs, checking which services
slow down boot, adding a swapfile, or simply installing the same handful of
apps on a fresh machine. Preen collects those jobs into a single, friendly
interface built for people who want the power of the terminal without
memorising it.

Three principles guide every screen.

1. **Show before you change.** Turn on Simulate and every action is written
   to the Logs page as the exact command that would run, with nothing
   executed. The same switch covers package installs, deletions, gsettings,
   icon packs, archives and service changes.
2. **Protect the system, not just the user.** Essential packages such as
   `gnome-shell`, `apt` and `systemd` cannot be bulk-removed, service names
   are validated before they reach `systemctl`, and archives are inspected
   for path traversal, links and device nodes before extraction.
3. **Tell the truth.** Deep Clean measures each item in bytes before you
   delete it, every command keeps its exit code, and failures appear in a
   dismissible banner plus the log instead of failing silently.

The app is lightweight by design. It runs only while open, speaks to the
system tools already installed on your machine, and its AppImage weighs
around 1 MB.

---

## Features at a glance

| Page | What you can do |
|---|---|
| **Dashboard** | Live CPU, memory, disk and swap cards, load average, kernel, uptime and power profile, plus a plain-language report of missing optional tools |
| **Install Apps** | 55 curated apps across 10 categories with search, source badges, status badges, quick-pick presets and bulk install, update and remove actions |
| **Manage Apps** | Installed Flatpak apps and graphical APT packages in one searchable list, with protected core packages clearly marked |
| **Deep Clean** | Sized scan of the APT cache, systemd journal, thumbnails, pip cache and trash, with select-all and a running total of reclaimable space |
| **Optimize System** | Package cleanup, GNOME animations, startup apps, power profile, swapfile size (1 to 8 GB) and ZRAM, applied only where settings actually changed |
| **Services** | Boot-time breakdown, slowest units, and start, stop, restart, enable and disable for systemd services, with a running-only filter |
| **Customize Look** | Light and dark theme, desktop text scaling, icon packs from validated archives, and reversible rounded-corner CSS |
| **Backup & Restore** | Timeshift snapshots with a saved-snapshot list, plus safe export and import of `~/.config` |
| **Logs** | Every command, exit code and error, with a text filter, auto-scroll toggle and one-click save |

The header bar holds the **Simulate** switch and a compact menu for
Preferences, Help and About. Preferences live in
`~/.config/preen/settings.json`, and settings from older 0.2.x releases are
migrated automatically.

---

## Installation

### Option 1: Debian package (recommended for Ubuntu, Zorin OS and Debian)

Download `preen_0.4.0_all.deb` from the
[latest release](https://github.com/mdadeel/Preen/releases/latest), then run:

```bash
sudo apt install ./preen_0.4.0_all.deb
preen
```

`apt` resolves the required GTK and psutil dependencies for you. Launch it
from the app menu as **Preen**, or type `preen` in a terminal.

### Option 2: AppImage (any distribution, no installation)

Download `Preen-0.4.0-x86_64.AppImage` from the
[releases page](https://github.com/mdadeel/Preen/releases/latest), make it
executable and run it. It uses the Python and GTK already on your system, so
the file stays small.

```bash
chmod +x Preen-0.4.0-x86_64.AppImage
./Preen-0.4.0-x86_64.AppImage
```

### Option 3: Python wheel

If you prefer pip and already have the GTK bindings installed:

```bash
pip install preen-0.4.0-py3-none-any.whl
preen
```

### Option 4: Run from a source checkout

```bash
# System dependencies (Debian and Ubuntu family)
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas polkitd tar xz-utils

# Optional tools unlock matching features
sudo apt install -y power-profiles-daemon systemd-zram-generator timeshift

# Install in editable mode and launch
python3 -m pip install -e .
python3 -m preen_tool.app
```

### Option 5: Build the packages yourself

```bash
# Debian package, no debhelper required
./packaging/build_deb.sh
sudo apt install -y ./dist/preen_0.4.0_all.deb

# AppImage
./packaging/build_appimage.sh
```

Everything is also wired into the Makefile. Run `make help` to see the full
list of targets.

### Verify the install

The built-in doctor checks Python, GTK, the package layout and every optional
tool without opening the window, which makes it handy over SSH:

```bash
preen --doctor
preen --doctor --json
```

Missing optional tools only disable the features that need them. The
Dashboard explains exactly which ones and why.

---

## First five minutes

1. Launch Preen. You land on the **Dashboard**, where the health panel lists
   any tools that are not installed yet.
2. Turn on **Simulate** in the top-right corner. An amber pill confirms the
   mode, and every mutating action becomes a dry run.
3. Open **Install Apps**, search for something such as `vlc`, tick it and
   press **Install Selected**.
4. Open **Logs**. You will see the full `flatpak` or `apt-get` command marked
   `[simulate] would run:`, proof that nothing was installed.
5. When you are comfortable, switch Simulate off and repeat the action for
   real. Root commands are batched into a single polkit prompt.

The same habit works everywhere: scan Deep Clean before cleaning, read the
boot analysis before touching services, and export your settings before
importing an archive.

---

## Command line

```bash
preen                         # start the graphical app
preen --simulate              # start with dry-run mode enabled
preen --doctor                # installation and dependency report, no GTK
preen --doctor --json         # the same report as machine-readable JSON
preen --check-catalog         # validate apps.json and presets.json
preen --version
```

The `zorin-optimizer` command still works as an alias for users upgrading
from the 0.2.x line.

---

## Development

```bash
make setup        # system dependencies plus an editable install
make check        # validate the app catalogue and presets
make test         # full regression suite (no root, GTK display or network)
make doctor       # headless diagnostics
make wheel        # build a wheel after check and test
make deb          # build the Debian package
make clean        # remove generated artefacts
```

The test suite runs entirely on fakes. `tests/fakes.py` provides a fake
Linux userspace with stand-ins for `flatpak`, `dpkg`, `gsettings`,
`pkexec`, `swapon`, `powerprofilesctl` and `timeshift`, while a fake GTK
walks every screen and handler. The suite currently contains 68 tests and
runs in about a second.

```bash
python3 -m unittest discover -s tests -v
```

When you add an app to `preen_tool/config/apps.json`, run `make check` so the
ID and package-name validators verify the entry.

---

## Safety model

- **Simulate first.** All mutating paths, including file writes and
  gsettings, check the simulate flag before acting. A dedicated test calls
  every mutating operation with Simulate on and asserts nothing is spawned
  or written.
- **Batched authorisation.** Privileged steps are joined into one shell
  script behind a single `pkexec` prompt, and every interpolated value is
  quoted with `shlex.quote`.
- **Package protection.** A frozen allowlist of essential APT packages is
  refused at removal time, and scanner rows pass strict regular-expression
  validation before becoming command arguments.
- **Archive hardening.** Tar extraction rejects absolute paths, parent
  traversal, symlinks, hardlinks, device nodes and unsafe permissions.
- **Diff-based tuning.** Optimize and Customize only apply settings that
  differ from the detected baseline, so an existing swapfile or theme is
  never clobbered by accident.
- **Atomic writes.** Preferences, desktop entries and CSS are written via
  temp files and `os.replace`, so an interrupted write cannot corrupt them.

---

## Project layout

```
preen_tool/
  app.py                  GTK-free entry point and friendly GTK error message
  cli.py                  headless doctor, catalogue validation and JSON output
  gui.py                  all GTK screens, styling and the serial task queue
  backend/
    apps.py               APT and Flatpak catalogue, detection and actions
    deepclean.py          sized scans and safe cleaning
    services.py           systemd units, boot analysis and validation
    performance.py        power profiles, swapfile and ZRAM
    system.py             cleanup, animations and startup applications
    ui_customization.py   themes, text scaling, icon packs and CSS
    backup.py             Timeshift integration and config archives
    dashboard.py          live system metrics and capability checks
    settings.py           validated preferences storage
    utils.py              command runner, outcomes and shared safety helpers
  config/
    apps.json             curated application catalogue (data, not code)
    presets.json          quick-pick bundles
packaging/                reproducible .deb and AppImage builders
tests/                    fake userspace, fake GTK and 68 regression tests
docs/                     user guide and architecture notes
```

---

## Contributing and licence

Pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the
workflow and coding rules, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the module map and threading contracts. The
[user guide](docs/USER_GUIDE.md) covers every page in plain language, and
[the changelog](CHANGELOG.md) records the history of each release.

Preen is released under the MIT licence. See [LICENSE](LICENSE) for the full
text.
