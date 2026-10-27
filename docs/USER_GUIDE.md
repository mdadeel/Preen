# User Guide

Zorin Optimizer installs apps, cleans up packages, and tunes your Zorin OS
system. This guide assumes no Linux experience.

> **The single most important feature is the Simulate switch.** Turn it on
> before trying anything. Nothing changes; the Logs page shows exactly what
> would have run.

---

## 1. Install

### Option A — Debian package (recommended)

```bash
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas polkitd tar xz-utils

cd ZorinOS-Optimizer
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
sudo apt install -y ../zorin-optimizer_0.2.0_all.deb
```

Launch it from the app menu (**Zorin Optimizer**) or run `zorin-optimizer`.

### Option B — Run from a source checkout

```bash
python3 -m pip install -e .
python3 -m zorin_optim_tool.app
```

### Optional tools

Install these only if you want the matching features:

```bash
sudo apt install power-profiles-daemon systemd-zram-generator timeshift
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

Missing tools are **not fatal**. The Dashboard → **Tool availability** panel
tells you exactly which features are unavailable, and `--doctor` prints the
same information in a terminal.

---

## 2. Your first five minutes

1. **Launch the app.** You land on the **Dashboard**.
2. **Read Tool availability.** If something is missing, install it or accept
   that the related feature will be greyed out / report an error.
3. **Turn on Simulate** (top-right switch). An amber banner confirms it.
4. Go to **Install Apps**, search for something (e.g. `vlc`), tick it and
   press **Install Selected**.
5. Open **Logs**. You will see `$ flatpak install ...` (or the APT command)
   with `[simulate] would run:` — proof that nothing was installed.
6. When you are happy, switch Simulate **off** and repeat the action for real.
   You will be asked for your password once per batch via polkit.

---

## 3. The pages

### Dashboard

- **Getting started** — the three-step safe workflow.
- **System at a glance** — CPU, RAM, disk, OS, kernel, uptime, power profile.
  Refreshes automatically (configurable in Preferences).
- **Tool availability** — plain-language warnings for missing `flatpak`,
  `apt-get`, `pkexec`, `gsettings`, `powerprofilesctl` or `timeshift`.
- **Refresh Status**, **Run Cleanup Now**, **Open Logs**.

### Install Apps

- **Preferred source** (`Flatpak` or `APT`) is a preference, not a restriction.
  If an app has no package for that source, the other one is used and the
  fallback is written to Logs.
- The badge next to each app shows which sources are available
  (`Flatpak`, `APT`, or `Flatpak + APT`). Hover for extra notes.
- **Status** shows `Installed (…)` / `Not installed`. Press **Refresh Status**
  after installing anything outside the app.
- **Search**, **Select all**, **Clear**, and **Quick picks** presets make large
  selections quick. The counter shows how many apps are ticked.
- **Install Selected** (green) is the primary action.
  **Uninstall Selected** (red) asks for confirmation.

> Uninstall acts on the format that is actually installed, not just the
> selected source.

### Manage Installed Apps

- Lists Flatpak apps and **graphical** APT applications (packages owning a
  `.desktop` launcher) — not thousands of libraries.
- Search, then **Update Selected** or **Uninstall Selected**.
- Rows marked **🔒 protected** are core desktop packages. Their checkboxes are
  disabled so you cannot break your session.

### Optimize System

- **Cleanup & desktop behaviour** — remove unused packages, disable GNOME
  animations, manage startup apps.
- **Memory & power** — 2 GB swapfile, ZRAM, power profile.
- Press **Apply Changes**. **Only settings you changed are applied** — pressing
  the button with nothing ticked does nothing. This is deliberate: it will not
  delete a swapfile you created earlier.
- **Reload Current Settings** re-reads the actual state of your machine.

### Customize Look

- **Appearance**: Light / Dark. Only GTK themes that exist on your system are
  applied; the GNOME `color-scheme` is always set.
- **Rounded corners** adds a clearly-marked, reversible block to
  `~/.config/gtk-3.0/gtk.css`. Restart apps to see it.
- **Install Icon Pack…** accepts `.tar.xz` / `.tar.gz` archives containing an
  `index.theme`. Unsafe archive entries are refused.

### Backup & Restore

- **Create Snapshot** / **Open Timeshift** — requires Timeshift to be installed.
- **Export Settings…** saves `~/.config` to a `.tar.xz` archive.
- **Import Settings…** restores it. The archive is inspected first: absolute
  paths, `../` traversal and links are refused. **Import overwrites matching
  files — export first.**

### Logs

- Every command, its exit code, stdout/stderr and any error are recorded here.
- **Save Log…**, **Clear**, and an **Auto-scroll** switch.
- Attach a saved log when reporting a problem.

---

## 4. Preferences & Help

**Preferences** (header bar) saves to
`~/.config/zorin-optimizer/settings.json`:

| Setting | Default | Meaning |
|---|---|---|
| Preferred package source | Flatpak | Pre-selected source on the Install page |
| Dashboard auto-refresh | 15 s | `Off` disables the periodic refresh |
| Start in Simulate mode | Off | Safer default for shared machines |
| Confirm destructive actions | On | Ask before uninstall / restore |
| Show dependency warnings | On | Startup banner when a tool is missing |

Source and safety options apply immediately; startup and refresh options apply
after a restart. If the file is corrupted it is silently reset to defaults —
the app will not crash.

**Help** shows the quick-start summary. **About** shows the version, licence
and project link.

---

## 5. Command line reference

```bash
zorin-optimizer                    # start the GUI
zorin-optimizer --simulate         # start with dry-run enabled
zorin-optimizer --doctor           # check installation and tools (no GTK)
zorin-optimizer --doctor --json    # same, machine-readable
zorin-optimizer --check-catalog    # validate apps.json / presets.json
zorin-optimizer --version
```

`--doctor` exits non-zero only if the catalogue is invalid, the Python version
is too old, or the installed package layout is broken. Missing external tools
are reported as notes/warnings.

---

## 6. Troubleshooting

| Symptom | What to do |
|---|---|
| App will not start / `python3-gi` error | `sudo apt install python3-gi gir1.2-gtk-3.0 python3-psutil`; then run `--doctor`. |
| "pkexec is required" | Install polkit: `sudo apt install polkitd` (or `policykit-1` on older releases). |
| Flatpak app not found | Check the ID on Flathub and `--check-catalog`. Also add the flathub remote (see §1). |
| APT package not found | Your repos may not have it (e.g. Timeshift needs a PPA). The Logs page shows the exact `apt-get` error. |
| Power profile does nothing | Install `power-profiles-daemon` and reboot. |
| Swapfile / ZRAM change failed | The Logs page shows the failing command; check that `systemd-zram-generator` is installed. |
| Theme did not change | GNOME 42+ uses `color-scheme`; some apps need a restart. Only installed GTK themes are applied. |
| An action failed | A red banner appears at the top. Open **Logs** for the full stderr, then **Save Log…**. |
| I want to undo a look change | Turn off **Rounded corners** and apply; the CSS block is removed. Re-select Light/Dark. |
| Preferences not applying | Restart the app — that is stated in the dialog. |

---

## 7. FAQ

**Is Simulate mode really safe?**
Yes. All 19 mutating actions are gated by it, including file writes, gsettings,
icon packs and config import. Read-only checks still run so statuses stay
accurate. A test calls every one of them with Simulate on and asserts no
mutating command is spawned and no file is created.

**Will it remove important system packages?**
No. Core packages (`gnome-shell`, `apt`, `python3`, …) are marked 🔒 protected
and their checkboxes are disabled. Scanner rows are also validated with a
strict pattern before becoming command arguments.

**Why does it ask for my password?**
APT, `/etc/fstab` and systemd changes need root. Commands are batched so you
get **one** polkit prompt per operation, not one per package.

**Where are my settings stored?**
`~/.config/zorin-optimizer/settings.json`. Your exported config archives are
ordinary `.tar.xz` files you choose the location of.

**Does it phone home?**
No. The only network activity is what `apt-get` or `flatpak` does when you ask
them to install something.

---

Need more? See [ARCHITECTURE.md](ARCHITECTURE.md) for developers,
[CONTRIBUTING.md](../CONTRIBUTING.md) to help out, or
[ROAST.md](ROAST.md) for the full list of bugs that used to be here.
