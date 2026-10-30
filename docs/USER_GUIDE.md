# Preen User Guide

Preen helps you set up, clean and tune a Linux desktop from one window. This
guide assumes no Linux experience and walks through every page.

> Turn on **Simulate** in the top-right corner before trying maintenance
> actions. Supported changes are previewed in Logs instead of applied. This is
> not a no-write sandbox: read-only checks still run, preferences and logs can
> be saved, and loading old settings may migrate a legacy configuration folder.
> If `ZOPTIM_SIMULATE=1` forces simulation, the switch stays locked on.

---

## 1. Install

### Option A: Run from source

On a Debian/Ubuntu-family system:

```bash
sudo apt install -y git python3 python3-gi gir1.2-gtk-3.0 python3-psutil
git clone https://github.com/mdadeel/Preen.git
cd Preen
python3 -m preen_tool.app --doctor
python3 -m preen_tool.app --simulate
```

If your default Python cannot import the system PyGObject package, use the
system Python, such as `/usr/bin/python3`, for the last two commands.

### Option B: Build a Debian package

Check the [releases page](https://github.com/mdadeel/Preen/releases) for
available assets. If a Debian package is attached, download the matching file;
otherwise, with `dpkg-deb` installed, build from a checkout:

```bash
./packaging/build_deb.sh
sudo apt install ./dist/preen_0.5.0_all.deb  # use the file the builder reports
preen --simulate
```

### Option C: Build an AppImage

On x86-64 Linux, `./packaging/build_appimage.sh` builds an AppImage from a
checkout. It needs the host's Python, GTK and PyGObject, and may download
`appimagetool` without verifying its checksum; the tool may also fetch its
runtime. Prefer a trusted pre-verified appimagetool AppImage supplied through
`APPIMAGETOOL` and verify its runtime. The builder checks the result's header
and version; the file is in `dist/`.

### Optional tools

Install these only if you want the matching features:

```bash
sudo apt install flatpak gsettings-desktop-schemas polkitd
sudo apt install power-profiles-daemon systemd-zram-generator timeshift
# Optional: Snap apps on the Manage Apps page, the Drivers page and the
# firewall toggle on Optimize System.
sudo apt install snapd ubuntu-drivers-common ufw
# Optional: add Flathub if you choose to use that Flatpak repository.
flatpak remote-add --if-not-exists flathub \
  https://flathub.org/repo/flathub.flatpakrepo
```

Some older distributions use `policykit-1` rather than `polkitd`. Preen can
start without these tools, but the corresponding features will not work until
they are installed. The Dashboard and `--doctor` report available capabilities.

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

The sidebar groups the eleven pages under Overview, Software, System and
Personal, with symbolic icons and a highlighted selected row. Use **Find a
page** at the top of the sidebar to filter by name. Section headers hide
while a search is active and return when you clear it. On smaller windows,
scroll the sidebar and page content to reach additional controls.

While a task runs, the header shows its name (for example "Installing apps")
and action buttons pause until it finishes; you can keep navigating, reading
Logs and using search boxes. Keyboard shortcuts: **F5** refreshes the visible
page, **Ctrl+F** jumps to its search box (or the sidebar page filter),
**Ctrl+A** selects everything on the Install, Manage and Deep Clean lists,
and **Escape** dismisses a notice banner.

### Dashboard

- A hero card with your operating system, kernel, uptime, power profile and
  load average.
- Four live metric cards for CPU, memory, disk and swap. Readings that cannot
  be measured are shown as unavailable, not as zero. The refresh interval
  is configurable in Preferences.
- Suggested next steps and a **Tool availability** panel when tools are missing.
- Shortcuts: **Refresh Status**, **Run Cleanup** and **Open Logs**.

### Install Apps

- Pick a preferred source with the segmented **Flatpak / APT** switch. If the
  catalogue has no entry for that source but has one for the other, Preen uses
  the other source and logs the fallback. This does not promise a retry after a
  repository or installation error.
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

- Lists Flatpak apps, Snap apps and graphical APT applications (packages that
  own a `.desktop` launcher), never thousands of libraries. A package that
  ships several launchers shows one row per launcher; removing any of them
  removes the owning package. Base snaps such as `core22` appear as
  **protected** rows. If snapd is not installed, snaps are simply absent from
  the list.
- After each scan Preen checks for updates (APT from the cached package
  index; Flatpak and Snap contact their stores). Matching rows show
  **Update available**; pressing **Update Selected** with nothing ticked
  selects those rows for you. Store checks can fail offline — the badge is
  best-effort and the Logs page says why.
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

Items include the APT cache, the system journal, old kernel packages,
thumbnails, pip cache and trash. Old-kernel cleanup always keeps the running
kernel plus one spare. Journal usage includes active files that cannot be
vacuumed, so the amount above the 100 MiB retention target is only an
upper-bound estimate. Trash deletion is permanent; thumbnails are
regenerated automatically.

**Automatic maintenance** (bottom card) installs a systemd timer that runs
the root-level cleanup tasks — package cache, unused packages, journal
vacuum, unused Flatpak runtimes — on a Daily, Weekly or Monthly schedule,
even when Preen is closed. Enabling asks for confirmation and one
administrator prompt; disabling removes the units again. The change is
previewed without touching the system while Simulate is on.

### Optimize System

- **Cleanup and desktop behaviour:** autoremove and autoclean packages,
  remove unused Flatpak runtimes, disable GNOME animations, and manage
  startup applications through a dedicated dialog.
- **Security:** a **Firewall (UFW)** toggle. Enabling blocks unsolicited
  incoming connections (this can affect file sharing or SSH). Like the other
  Optimize System rows, the change is staged and applied with **Apply
  Changes**; disabling the firewall asks for confirmation there. The row is
  disabled when ufw is missing or its state cannot be read.
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

### Drivers

- Runs `ubuntu-drivers devices` and lists the hardware it offers driver
  packages for, with every candidate package named on the row and the
  **recommended** one badged. Search filters the rows.
- Tick devices and press **Install Selected**, or use **Auto Install
  (recommended)** to let ubuntu-drivers choose. Both ask for confirmation
  and one administrator prompt. The list is rescanned afterwards.
- The page says so when `ubuntu-drivers` is not installed (the
  `ubuntu-drivers-common` package provides it) and when detection reports
  errors; see Logs for details.

### Customize Look

- Under **Preen appearance**, choose **Follow system**, **Light** or **Dark**,
  then press **Apply Look Changes**. This changes Preen only; it does not
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
- Applying the look does not reset Optimize System, and optimizing does not
  reset the look; each page stages and applies its own changes.
  App lists use installed icons where available, bundled marks for some
  catalogue entries, and generic initials when no matching icon is available.

### Backup & Restore

- **Create Snapshot** requests an on-demand Timeshift snapshot, **Open
  Timeshift** launches its own window, and **Refresh List** requests
  administrator authorization to show saved snapshots. The startup check
  never prompts; it may show unavailable until you refresh. A refresh is not
  run in Simulate mode.
- **Export Settings** saves regular files under `~/.config` to a `.tar.xz`
  archive, skipping named caches and links. The archive can include credentials
  and private settings; Preen does not encrypt it. Store and share it carefully.
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
| Start in Simulate mode | Off | Turn on to start future sessions in Simulate mode |
| Confirm full package updates | On | Ask before Update All; cleanup, uninstall and restore always require confirmation |
| Show dependency warnings | On | Startup banner when a tool is missing |

Source and safety options apply immediately. Startup and refresh options
apply after a restart. A corrupted settings file is reset to defaults
instead of crashing the app.

---

## 5. Command line reference

These examples assume Preen is installed. From a source checkout, replace
`preen` with `python3 -m preen_tool.app`.

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
Supported maintenance operations, including cleanup, desktop settings, icon
packs, archives and service changes, are previewed instead of applied. Tests
exercise selected command and file changes with Simulate on. Read-only checks
still run, preferences or logs can be saved, and legacy settings can migrate;
it is not a no-write sandbox or a substitute for a backup.

**Will it remove important system packages?**
Preen's direct app-uninstall paths block a defined set of core APT package
names such as `gnome-shell`, `apt` and `python3`, disable their selection and
validate scanned names. APT autoremove and dependency changes can affect other
packages, and Simulate does not run the package solver to predict every effect.
Review removal requests and keep a backup.

**Why does it ask for my password?**
APT, `/etc/fstab` and systemd changes need root. Related package commands
are batched where possible; separate privileged steps can prompt separately.

**Where are my settings stored?**
In `~/.config/preen/settings.json`. Exported config archives go wherever you
choose in the file chooser.

**Does it phone home?**
The current app has no built-in telemetry or log upload. APT, Flatpak,
Flathub setup and other external tools can contact repositories or services
under their own policies. Logs and config archives can contain sensitive data;
see the [privacy policy](../PRIVACY.md).
