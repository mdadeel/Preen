# ZorinOS Optimizer

A GTK 3 tool to install/remove APT and Flatpak apps, clean up packages, tune
power/swap/ZRAM, customise the look, and back up your config on Zorin OS.

> Version **0.2.0** is a reliability rewrite. See [`docs/ROAST.md`](docs/ROAST.md)
> for the (brutal) audit of v0.1.0 and the full list of fixes.

---

## ✨ Features

- **Install Apps** — 45 curated apps with real Flathub IDs, APT alternatives,
  search, status badges, presets, install / update / uninstall / update-all.
- **Manage Apps** — scan installed Flatpak apps and *graphical* APT packages;
  bulk update/uninstall; core desktop packages are locked.
- **Optimize System** — APT/Flatpak cleanup, GNOME animations, startup apps,
  power profiles, swapfile, ZRAM. Only settings you actually changed are applied.
- **Customize Look** — light/dark theme, safe icon-pack installer, rounded
  corners with reversible CSS.
- **Backup & Restore** — Timeshift snapshots, export/import `~/.config`.
- **Dashboard & Logs** — live CPU/RAM/disk/OS info, saveable live log.
- **Simulate mode** — dry-runs **every** mutating action, including gsettings,
  file writes, icon packs and backups.

---

## ✅ Prerequisites

```bash
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas 'polkitd | policykit-1' \
  tar xz-utils
sudo apt install -y power-profiles-daemon systemd-zram-generator  # optional features
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

`pkexec` is used for APT, fstab and systemd changes; you will get one polkit
prompt per batch, not one per package.

---

## 🚀 Install and run

```bash
cd ZorinOS-Optimizer
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
sudo apt install -y ../zorin-optimizer_0.2.0_all.deb
zorin-optimizer
```

Or run from a checkout:

```bash
python3 -m pip install -e .      # or: sudo apt install python3-psutil
python3 -m zorin_optim_tool.app
```

### Headless diagnostics (no GTK, no display needed)

```bash
zorin-optimizer --doctor           # dependency + installation report
zorin-optimizer --doctor --json    # machine-readable
zorin-optimizer --check-catalog    # validate apps.json / presets.json
zorin-optimizer --version
zorin-optimizer --simulate         # start the GUI in dry-run mode
```

`--doctor` exits non-zero if the catalogue is broken or the installed package
layout is incomplete. Missing external binaries (flatpak, timeshift, …) are
reported as warnings because they only disable the features that need them.

---

## 🧪 Tests

The suite uses fake system binaries, so it never installs or deletes anything:

```bash
python3 -m unittest discover -s tests -v
# or: pytest -q
```

It covers the wheel contents, catalogue validity, two-query status detection,
command batching, polkit handling, simulate mode for all 19 mutating actions,
tar path-traversal defence, desktop-entry edits, CSS idempotency, and the GUI
import surface.

A ready-made GitHub Actions workflow lives at
[`docs/ci-workflow.yml.example`](docs/ci-workflow.yml.example); copy it to
`.github/workflows/ci.yml` to run those checks on every push.

---

## 🧭 Usage tips

- Turn on **Simulate** in the header before trying anything you are unsure
  about. The Logs page shows the exact argv that would have run.
- The source selector is a *preference*: if an app has no Flatpak it falls back
  to APT (and says so in the log), and vice versa.
- Uninstall acts on the format that is really installed, not just the selected
  source.
- "Manage Apps" lists packages owning `.desktop` launchers, not all 2,000+
  installed libraries.

---

## 📦 Packaging notes

- Debian packaging lives in `debian/`; the Python wheel is built from
  `pyproject.toml` using automatic package discovery, so `backend/` and
  `config/*.json` are actually shipped.
- Desktop launcher: `data/zorin-optimizer.desktop`.
- Build outputs, `__pycache__`, egg-info and virtualenvs are gitignored.

---

## 🛣️ Roadmap

- CPU frequency graph and per-app sizes
- Accent colour picker with persistence
- Debloat helper (orphan/large/unused app suggestions)
- Driver/kernel helpers (HWE/LTS)

## 📄 License

MIT
