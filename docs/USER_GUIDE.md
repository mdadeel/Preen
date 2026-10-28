# Preen User Guide

Preen helps you set up, clean and tune a Linux desktop from one window. This
guide assumes no Linux experience and walks through every page.

> The single most important control is the **Simulate** switch in the
> top-right corner. Turn it on before trying anything: nothing changes, and
> the Logs page shows exactly what would have run.

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

Missing tools are never fatal. The Dashboard tool panel explains which
features are unavailable, and `preen --doctor` prints the same report in a
terminal.

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
   You enter your password once per batch through polkit.

---

## 3. The pages

The sidebar groups the nine pages under Overview, Software, System and
Personal, each with a coloured symbol tile. Use the **Search** field at the
top of the sidebar to jump straight to a page: type part of its name, such
as `clean` or `backup`, and the list filters to the matches. The section
headers hide while a search is active and return when you clear the field.
The currently selected page is shown as a solid blue row.

### Dashboard

- A hero card with your operating system, kernel, uptime, power profile and
  load average.
- Four live metric cards: CPU, memory, disk and swap, each with a progress
  bar in its own accent colour. They refresh automatically, and the interval
  is configurable in Preferences.
- A three-step getting-started checklist.
- A **Tool availability** panel with plain-language warnings.
- Shortcuts: **Refresh Status**, **Run Cleanup Now** and **Open Logs**.

### Install Apps

- Pick a preferred source with the segmented **Flatpak / APT** switch. It is
  a preference, not a restriction: when an app is missing from one source,
  the other is used automatically and the fallback is logged.
- The badge next to each app shows the available source or sources. Hover
  for notes.
- Search, **Select all**, **Clear** and **Quick picks** presets make large
  selections fast. The counter shows what is ticked.
- **Install Selected** is the primary action. **Update Selected**,
  **Update All** and **Uninstall Selected** share the same list, and
  uninstall always asks for confirmation.

### Manage Apps

- Lists Flatpak apps and graphical APT applications (packages that own a
  `.desktop` launcher), never thousands of libraries.
- Search, then **Update Selected** or **Uninstall Selected**.
- Rows marked **protected** are core desktop packages. Their checkboxes are
  disabled so a cleanup cannot break your session.

### Deep Clean

1. Press **Scan Now**. Every item shows the space it reclaims before
   anything is deleted.
2. Tick what you want, or use **Select all** and **Clear**. The counter
   shows the selected total.
3. Press **Clean Selected**. Root items share one polkit prompt.

Items include the APT package cache, the systemd journal (vacuumed to keep
the newest 100 MB), thumbnails, the pip cache and the trash. Thumbnails are
regenerated automatically.

### Optimize System

- **Cleanup and desktop behaviour:** autoremove and autoclean packages,
  remove unused Flatpak runtimes, disable GNOME animations, and manage
  startup applications through a dedicated dialog.
- **Memory and power:** create or remove a swapfile with a selectable size
  (1, 2, 4 or 8 GB), enable ZRAM, and choose a power profile.
- Only settings that differ from the detected baseline are applied, so
  pressing apply with no changes does nothing.

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

- Switch between **Light** and **Dark**, or apply the theme immediately.
- Choose a **Text size** preset (85% to 125%) for desktop-wide scaling.
- Install an icon pack from a `.tar.xz` or `.tar.gz` archive. Unsafe archive
  entries are refused.
- Add reversible rounded corners through a guarded block in
  `~/.config/gtk-3.0/gtk.css`.

### Backup & Restore

- **Create Snapshot** requests a Timeshift snapshot, **Open Timeshift**
  launches its own window, and **Refresh List** shows the snapshots already
  saved on this machine.
- **Export Settings** saves `~/.config` to a `.tar.xz` archive, skipping
  caches and links.
- **Import Settings** restores an archive inside `~/.config` and nowhere
  else. Import overwrites matching files, so export first if you are unsure.

### Logs

- Every command, exit code, stdout fragment and error is recorded here.
- Use **Filter log** to find a line, and the **Auto-scroll** switch to hold
  a position while new lines arrive.
- **Save Log** writes the full history to a text file you can attach to a
  support request.

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
| Confirm destructive actions | On | Ask before uninstall or restore |
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
| Swapfile or ZRAM change failed | Open Logs for the failing command and check that `systemd-zram-generator` is installed. |
| Theme did not change | GNOME 42 and newer use `color-scheme`. Some apps need a restart, and only installed GTK themes are applied. |
| An action failed | Read the banner and open Logs for the full stderr, then use **Save Log**. |
| I want to undo a look change | Switch off rounded corners and apply, then re-select the Light or Dark theme. |

---

## 7. FAQ

**Is Simulate mode really safe?**
Yes. Every mutating operation, including file writes, gsettings, icon packs,
archives and service changes, is gated by it. A test calls each one with
Simulate on and asserts that no command is spawned and no file is written.

**Will it remove important system packages?**
No. Core packages such as `gnome-shell`, `apt` and `python3` are protected,
their checkboxes are disabled, and scanner rows pass strict validation
before becoming command arguments.

**Why does it ask for my password?**
APT, `/etc/fstab` and systemd changes need root. Commands are batched so you
see one polkit prompt per operation, not one per package.

**Where are my settings stored?**
In `~/.config/preen/settings.json`. Exported config archives go wherever you
choose in the file chooser.

**Does it phone home?**
No. The only network activity is what `apt-get` or `flatpak` performs when
you ask them to install or update something.
