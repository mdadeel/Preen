# Preen User Guide

Preen helps you set up, clean and tune a Linux desktop from one window. This
guide assumes no Linux experience and walks through every page.

> The single most important control is the **Simulate** switch in the
> top-right corner. Turn it on before trying maintenance actions: they do not
> change the system, and Logs shows what would have run. When the environment
> variable `ZOPTIM_SIMULATE=1` forces simulation, the switch stays locked on.

---

## 1. Install

### Option A: Debian package (recommended)

Download `preen_0.4.0_all.deb` from the
[releases page](https://github.com/mdadeel/Preen/releases/latest), then:

```bash
sudo apt install ./preen_0.4.0_all.deb
preen
```

### Option B: AppImage (no installation)

```bash
chmod +x Preen-0.4.0-x86_64.AppImage
./Preen-0.4.0-x86_64.AppImage
```

### Option C: Run from a source checkout

```bash
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas polkitd tar xz-utils
python3 -m pip install -e .
python3 -m preen_tool.app
```

### Optional tools

Install these only if you want the matching features:

```bash
sudo apt install power-profiles-daemon systemd-zram-generator timeshift
flatpak remote-add --if-not-exists flathub \
  https://flathub.org/repo/flathub.flatpakrepo
```

Preen can start without these optional tools, but the corresponding features
will not work until they are installed. The Dashboard also identifies missing
required tools, and `preen --doctor` prints a capability report in a terminal.

---

## 2. Your first five minutes

1. Launch Preen. You land on the **Dashboard**.
2. Read the **Tool availability** panel and install anything you need.
3. Turn on **Simulate**. An amber pill appears in the window.
4. Open **Install Apps**, search for something such as `vlc`, tick it and
   press **Install Selected**.
5. Open **Logs**. You will see the exact command prefixed with
   `[simulate] would run:`, proof that nothing was installed.
6. When you are happy, switch Simulate off and repeat the action for real.
   Privileged commands use polkit and may prompt for authentication.

---

## 3. The pages

The sidebar groups the nine pages under Overview, Software, System and
Personal, with symbolic icons and a highlighted selected row. Use **Find a
page** at the top of the sidebar to filter by name. Section headers hide
while a search is active and return when you clear it. On smaller windows,
scroll the sidebar and page content to reach additional controls.

### Dashboard

- A hero card with your operating system, kernel, uptime, power profile and
  load average.
- Four live metric cards for CPU, memory, disk and swap. Readings that cannot
  be measured are shown as unavailable, not as zero. The refresh interval
  is configurable in Preferences.
- Suggested next steps and a **Tool availability** panel when tools are missing.
- Shortcuts: **Refresh Status**, **Run Cleanup** and **Open Logs**.

### Install Apps

- Pick a preferred source with the segmented **Flatpak / APT** switch. It is
  a preference, not a restriction: when an app is missing from one source,
  the other is used automatically and the fallback is logged.
- The badge shows catalogue sources; the status shows installed, not installed,
  unavailable or error. Preen does not claim that an update is available without
  a real update check. Failed package scans are not treated as proof that a
  package is absent.
- Search, **Select all**, **Clear** and **Quick picks** presets make large
  selections fast. The counter shows what is ticked.
- **Install Selected** is the primary action. **Update Selected**,
  **Update All** and **Uninstall Selected** share the same list, and
  uninstall always asks for confirmation.

### Manage Apps

- Lists Flatpak apps and graphical APT applications (packages that own a
  `.desktop` launcher), never thousands of libraries.
- Search, then **Update Selected** or **Uninstall Selected**. A scan warning
  means the list may be incomplete; see Logs for the cause.
- Rows marked **protected** are core desktop packages. Their checkboxes are
  disabled and the backend also blocks their removal.

### Deep Clean

1. Press **Scan Now**. Sizes are estimates, not guarantees of reclaimed disk
   space. An unreadable item is marked **Unavailable** instead of zero.
2. Tick what you want, or use **Select all** for measurable nonempty items.
   An unavailable-size item can be selected individually, with care.
3. Press **Clean Selected** and confirm. APT and journal actions are separate
   privileged steps and may each request polkit authentication.

Items include the APT cache, journal, thumbnails, pip cache and trash. Journal
usage includes active files that cannot be vacuumed, so the amount above the
100 MiB retention target is only an upper-bound estimate. Trash deletion is
permanent; thumbnails are regenerated automatically.

### Optimize System

- **Cleanup and desktop behaviour:** autoremove and autoclean packages,
  remove unused Flatpak runtimes, disable GNOME animations, and manage
  startup applications through a dedicated dialog.
- **Memory and power:** create or remove a swapfile with a selectable size
  (1, 2, 4 or 8 GB), enable ZRAM, and choose a power profile. The profile
  and animation controls are disabled if their current state cannot be read.
- An existing inactive `/swapfile` is never reformatted. Preen leaves custom
  or edited ZRAM configuration alone; it only removes the configuration it
  created (including the unchanged format from older Preen versions).
- Only settings that differ from the detected baseline are applied. Reloading
  optimization settings does not discard staged changes on Customize Look.

### Services

- **Boot time** card with the firmware, loader, kernel and userspace
  breakdown plus the slowest units.
- Searchable list of systemd services with status chips: green for running,
  red for failed, grey for stopped. Use **Running only** to shrink the list,
  and the counter shows how many rows match.
- **Start**, **Stop**, **Restart**, **Enable** and **Disable** act on the
  selected unit. Stop, restart and disable ask for confirmation, and unit
  names are validated before they reach `systemctl`.

### Customize Look

- Under **Preen appearance**, choose **Follow system**, **Light** or **Dark**
  and select **Apply Preen Appearance**. This changes Preen only; it does not
  change GNOME's colour scheme or GTK theme. Your choice is saved in Preen's
  preferences. Follow system reads GNOME appearance where available and uses
  dark if no desktop appearance has been detected. Explicit Light/Dark choices stay fixed when
  the desktop changes. In Simulate mode the change is previewed, not saved.
  If an older Preen version changed your desktop theme, restore it in your
  desktop's Appearance settings; Preen cannot know your previous choice.
- **Desktop-wide options** are separate and affect other applications. Choose
  a **Desktop text size** preset (85% to 125%), or use reversible GTK 3
  rounded corners. Existing custom scaling is preserved until explicitly
  changed; unreadable scaling is unavailable. Applying these options asks for
  confirmation and rounded corners write a guarded block in
  `~/.config/gtk-3.0/gtk.css`.
- **Install Desktop Icon Pack** installs an archive and activates its icon
  theme across GNOME after confirmation. Unsafe entries are refused. If a
  theme of the same name exists, the previous contents are kept under
  `~/.icons/.preen-backups/`.
- Applying only Preen appearance preserves staged text-size, rounded-corner and
  optimization changes. Reloading the look does not reset Optimize System.
  App lists use installed icons where available, bundled marks for some
  catalogue entries, and generic initials when no matching icon is available.

### Backup & Restore

- **Create Snapshot** requests an on-demand Timeshift snapshot, **Open
  Timeshift** launches its own window, and **Refresh List** requests
  administrator authorization to show saved snapshots. The startup check
  never prompts; it may show unavailable until you refresh. A refresh is not
  run in Simulate mode.
- **Export Settings** saves `~/.config` to a `.tar.xz` archive, skipping
  caches and links.
- **Import Settings** inspects the archive in the background and asks before
  overwriting matching files. Unsafe entries or existing destination symlinks
  are refused; export first if you are unsure. A disk or permission error
  during extraction may leave some earlier files restored.

### Logs

- Command output, errors, exit codes and callback tracebacks appear here with
  severity colours. Text can be selected and copied.
- Use **Filter log** to find lines, **Auto-scroll** to hold a position, and
  **Clear Log** to discard the retained history.
- **Save Log** writes the retained history, regardless of the active filter.
  The most recent 4,000 lines are kept in memory; older lines are discarded.

---

## 4. Preferences and Help

Open the menu button in the header bar to find Preferences, Help and About.
Preferences are saved to `~/.config/preen/settings.json`.

| Setting | Default | Meaning |
|---|---|---|
| Preferred package source | Flatpak | Pre-selected source on the Install page |
| Dashboard auto-refresh | 15 s | `Off` stops the periodic refresh |
| Page shown on startup | Dashboard | Any sidebar page can open first |
| Start in Simulate mode | Off | Safe default for shared machines |
| Confirm full package updates | On | Ask before Update All; cleanup, uninstall and restore always require confirmation |
| Show dependency warnings | On | Startup banner when a tool is missing |

Source and safety options apply immediately. Startup and refresh options
apply after a restart. A corrupted settings file is reset to defaults
instead of crashing the app.

---

## 5. Command line reference

```bash
preen                         # start the GUI
preen --simulate              # start with dry-run enabled
preen --doctor                # check installation and tools (no GTK)
preen --doctor --json         # machine-readable report
preen --check-catalog         # validate apps.json and presets.json
preen --version
```

`--doctor` exits non-zero only when the catalogue is invalid, Python is too
old or the installed package layout is broken. Missing external tools are
reported as warnings.

---

## 6. Troubleshooting

| Symptom | What to do |
|---|---|
| App will not start or a `python3-gi` error appears | Install `python3-gi gir1.2-gtk-3.0 python3-psutil`, then run `preen --doctor`. |
| "pkexec is required" | Install polkit with `sudo apt install polkitd` (or `policykit-1` on older releases). |
| Flatpak app not found | Check the ID on Flathub and run `preen --check-catalog`. Add the flathub remote if needed. |
| APT package not found | Your repositories may not carry it. The Logs page shows the exact `apt-get` error. |
| Power profile does nothing | Install `power-profiles-daemon` and reboot. |
| Swapfile or ZRAM change failed | Check Logs and install `systemd-zram-generator` if needed. Preen refuses to overwrite an existing inactive swapfile or a custom ZRAM configuration. |
| Preen appearance did not change | Turn off Simulate and apply the desired Preen appearance. Follow system needs readable GNOME appearance settings; otherwise it falls back to dark. Other apps are intentionally unchanged. |
| Preen's AppImage has a generic dock icon on Wayland | Integrate the AppImage with your desktop's AppImage integration tool so the shell can find its launcher. The Debian package installs the launcher and icon. |
| Snapshot list is unavailable | Install Timeshift and choose **Refresh List** to authorize the read, or open Timeshift directly. Simulate mode does not refresh it. |
| An action failed | Read the banner and open Logs for the full stderr, then use **Save Log**. |
| I want to undo a look change | Select Follow system for Preen. For desktop-wide changes, set the previous text size/icon theme and switch off rounded corners; confirm the changes. |

---

## 7. FAQ

**Is Simulate mode really safe?**
Maintenance operations, including cleanup, gsettings, icon packs, archives
and service changes, are gated by it. Tests exercise command and file changes
with Simulate on. Saving Preen preferences or a log is still allowed.

**Will it remove important system packages?**
No. Core packages such as `gnome-shell`, `apt` and `python3` are protected,
their checkboxes are disabled, and scanner rows pass strict validation
before becoming command arguments.

**Why does it ask for my password?**
APT, `/etc/fstab` and systemd changes need root. Related package commands
are batched where possible; separate privileged steps can prompt separately.

**Where are my settings stored?**
In `~/.config/preen/settings.json`. Exported config archives go wherever you
choose in the file chooser.

**Does it phone home?**
No. The only network activity is what `apt-get` or `flatpak` performs when
you ask them to install or update something.
