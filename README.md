# ZorinOS Optimizer

A modern, lightweight optimization and app-setup tool for Zorin OS. One-click installs, safe optimizations, and clear controls for beginners and power users.

<p align="center">
  <img src="https://img.shields.io/badge/OS-Zorin%20OS-0aa0ff" alt="Zorin OS" />
  <img src="https://img.shields.io/badge/GUI-GTK%203-4c9" alt="GTK 3" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
</p>

---

## ✨ Highlights
- App Installer with APT/Flatpak
  - Install Selected • Update Selected • Update All • Uninstall Selected
  - Presets for quick setups (Developer, Gamer, Creative, Minimalist)
  - Status badges: Installed / Not installed
- Manage Installed Apps
  - Scan all installed Flatpaks and APT packages
  - Bulk Update/Uninstall selected
- Optimize System
  - Cleanup (apt autoremove/autoclean, flatpak uninstall --unused)
  - Toggle GNOME animations, manage startup apps
  - Power profile switch (balanced/power-saver/performance), Swapfile, ZRAM
- Customize Look
  - Light/Dark theme, install icon pack (.tar.xz), rounded corners (user CSS)
- Backup & Restore
  - Timeshift snapshot launcher, Export/Import ~/.config as tarball
- System Dashboard & Logs
  - CPU/RAM/Disk/OS info, quick Cleanup, live logs
- Safety: Simulate Mode toggle to dry-run all mutating actions

---

## 🖼️ Screenshots
Place screenshots in `docs/screenshots/` and link them here.

---

## ✅ Prerequisites
Install system packages:

```bash path=null start=null
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
  flatpak gsettings-desktop-schemas power-profiles-daemon policykit-1 \
  tar xz-utils unzip
```

Enable Flathub (optional — the app can add it too):

```bash path=null start=null
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

---

## 🚀 Install and Run
Simplest: build and install the .deb, then run.

```bash path=null start=null
cd "ZorinOS Optimizer"
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign
sudo apt install -y ../zorin-optimizer_0.1.0_all.deb
zorin-optimizer
```

Developer run (without installing):

```bash path=null start=null
python3 -m zorin_optim_tool.app
```

---

## 🧭 Usage Tips
- Use the Simulate toggle in the header to preview actions safely (no system changes).
- Switch between APT and Flatpak sources on the Install page.
- Use Manage Apps to bulk update/uninstall installed APT/Flatpak titles.
- Backup & Restore lets you export/import `~/.config` and launch Timeshift.

---

## 📦 Packaging Notes
- Native Debian packaging included under `debian/`
- Installs a desktop launcher: `zorin-optimizer`
- Uses `pkexec` for privileged tasks (APT, swap, zram). You may see a Polkit prompt.

---

## 🛣️ Roadmap
- CPU freq monitor and power profile detection in Dashboard
- Accent color picker and persistence for look tweaks
- Debloat helper (orphan/large/unused app suggestions)
- Driver helpers and kernel switcher (HWE/LTS)

---

## 🤝 Contributing
PRs welcome! Suggested areas: new presets, more open-source apps, improved localization, and UX polish.

---

## 📄 License
MIT
