# ZorinOS Optimizer - Fix Implementation Plan

This document outlines the plans to fix the identified bugs, security flaws, performance bottlenecks, and UX issues in ZorinOS-Optimizer.

---

## 1. Fix Tar Bomb Vulnerability in Backup Restore
* **Target:** [`zorin_optim_tool/backend/backup.py`](file:///home/adeel/Documents/projects/ZorinOS-Optimizer/zorin_optim_tool/backend/backup.py)
* **Plan:** 
  * Rewrite `import_configs` to validate each member's target path using `os.path.commonpath`.
  * Filter members before extracting to ensure they stay strictly within `~/.config`.
  * Use the `filter` argument in `tarfile.extractall` if using modern Python, or safely iterate and extract members individually.

---

## 2. Fix Broken Presets in `presets.json`
* **Target:** [`zorin_optim_tool/config/presets.json`](file:///home/adeel/Documents/projects/ZorinOS-Optimizer/zorin_optim_tool/config/presets.json)
* **Plan:**
  * Map `Gamer Pack` keys directly to `["steam", "lutris", "mangohud"]`.
  * Map `Creative Pack` keys directly to `["gimp", "krita", "obs", "inkscape"]`.
  * Update `presets.json` to match these application IDs defined in `apps.json`.

---

## 3. Consolidate Swapfile Setup Commands (Reduce Polkit Prompts)
* **Target:** [`zorin_optim_tool/backend/performance.py`](file:///home/adeel/Documents/projects/ZorinOS-Optimizer/zorin_optim_tool/backend/performance.py)
* **Plan:**
  * Combine the 5 separate commands for swapfile creation into a single `pkexec bash -lc "..."` string command.
  * Combine the 2 disable swapfile commands into a single `pkexec` invocation.

---

## 4. UI Scanning Optimization (Gtk ListBox Freeze)
* **Target:** [`zorin_optim_tool/app.py`](file:///home/adeel/Documents/projects/ZorinOS-Optimizer/zorin_optim_tool/app.py)
* **Plan:**
  * Instead of dumping all 2,000+ system APT packages into the UI ListBox, we will filter the APT packages to only show user-installed graphical apps (checking if they have a desktop launcher file or if they are in our `apps.json` catalog).

---

## 5. Safely Handle Rounded Corners CSS
* **Target:** [`zorin_optim_tool/backend/ui_customization.py`](file:///home/adeel/Documents/projects/ZorinOS-Optimizer/zorin_optim_tool/backend/ui_customization.py)
* **Plan:**
  * Wrap the injected css rule with comment guards:
    `/* BEGIN ZORIN_OPTIMIZER_ROUNDED_CORNERS */`
    `window, dialog, .background { border-radius: 10px; }`
    `/* END ZORIN_OPTIMIZER_ROUNDED_CORNERS */`
  * ON toggle: Check if the guard exists before appending.
  * OFF toggle: Strip only the content between/including the comment guards.
