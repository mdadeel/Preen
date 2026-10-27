# Preen — Rebrand + Deep Clean + Services/Boot + Frosted Glass

**Goal:** Rebrand Zorin Optimizer to **Preen** ("System setup for Linux"), add two real feature pages (Deep Clean with size preview; systemd Services with boot-time breakdown), and a frosted-glass CSS pass.

**Architecture:** New backend modules `deepclean.py` and `services.py` follow the existing rules (mutating commands go through `run_cmd(mutate=True)` so Simulate mode gates them; pure parsers are separate functions for testability). GUI adds two stack pages wired into the existing sidebar/page contract. Rename is mechanical (`git mv` + import rewrite).

**Tech:** Python 3.8+, GTK 3, systemd CLI parsing, unittest with fake GTK.

## Global Constraints
- App display name: **Preen**; tagline: "System setup for Linux"; APP_ID `io.github.mdadeel.Preen`
- Python module renamed `preen_tool` → `preen_tool` (all imports updated)
- Every mutating command uses `run_cmd(..., mutate=True)`; unit names validated against `^[A-Za-z0-9@._\-\\]+\.service$`
- Test contract: handler names, row attributes, `app_rows` preserved; stack page count test updated 7 → 9
- `make lint` + `make test` green after every task; GUI smoke test at the end

---

### Task 1: Rebrand to Preen (branding + module + packaging)
Files: `git mv preen_tool preen_tool`; rewrite imports (`sed s/preen_tool/preen_tool/`) in all source/test files; `pyproject.toml` (name `preen`, version `0.3.0`, script `preen = "preen_tool.app:main"` + keep `zorin-optimizer` alias, packages include `preen_tool*`, package-data); `gui.py` APP_NAME/APP_ID/tooltip; rename `data/zorin-optimizer.desktop` → `data/preen.desktop` (Name=Preen, Exec=preen, WMClass=preen, new keywords); `debian/control` (Source/Package `preen`, description), `debian/install` (preen.desktop), `debian/changelog` (0.3.0 entry); README headline/quick-start/CLI name; CHANGELOG 0.3.0 section.
Verify: `python3 -m preen_tool.app --version` prints 0.3.0; `make lint && make test` pass; commit.

### Task 2: Frosted-glass CSS pass (gui.py `_CSS` only)
- Window: `background-image: linear-gradient(180deg, alpha(@theme_selected_bg_color,0.05), alpha(@theme_fg_color,0.02) 40%, transparent)` over `@theme_bg_color`.
- `.card`/`.stat-card`: `background-color: alpha(@theme_base_color, 0.82)`; sidebar `alpha(@theme_base_color, 0.55)` + existing fg tint; actionbar translucent to match.
- Soft inner top highlight on cards: `background-image: linear-gradient(to bottom, alpha(@theme_fg_color,0.02), transparent 40px)`.
Verify: tests + GUI smoke (CSS parse errors would print to stderr); commit.

### Task 3: Deep-clean backend (`preen_tool/backend/deepclean.py` + tests)
Pure/testable helpers:
- `du_size(path) -> int` (os.walk, skip missing)
- `parse_journal_usage(text) -> int` (parses "Archived and active journals take up 1.2 G" / "500.0 M" / bytes)
- `format_size(n) -> str` ("1.2 GB")
- `scan_cleanable() -> List[dict]` items: apt cache `/var/cache/apt/archives` (root clean), journal via `journalctl --disk-usage` (root vacuum), thumbnails `~/.cache/thumbnails` (user clean), trash `~/.local/share/Trash/files` (user clean). Each: `{key, label, detail, size, root}`; missing paths → size 0 and kept (shown as "0 B").
- `clean_user_paths(keys)` — simulate check first (`ok("[simulate] would clean …")`), else `shutil.rmtree` contents of thumbnails/trash; returns Outcome.
- `clean_apt_cache(log=None)` → `Report.run(["apt-get","clean"], use_pkexec=True, mutate=True)`
- `vacuum_journal(log=None)` → `["journalctl","--vacuum-size=100M"]`, use_pkexec, mutate.
Tests: parsers (G/M/bytes strings), `format_size`, `clean_user_paths` respects Simulate (tmpdir files survive), deletes when simulate off, unknown key → fail Outcome. Commit.

### Task 4: Services + boot backend (`preen_tool/backend/services.py` + tests)
- `parse_list_units(text) -> List[dict]` (5-column `list-units --type=service --all --no-legend` output: unit/load/active/sub/description)
- `parse_unit_files(text) -> Dict[str, str]` (unit → enabled/disabled/…)
- `list_services() -> List[dict]` merges both (id, description, active, sub, unit_state)
- `set_service_state(unit, action, log=None)` — validate unit regex + action in {enable,disable,start,stop}, then `run_cmd(["systemctl", action, unit], use_pkexec=True, mutate=True)`; Outcome via Report.
- `parse_analyze(text) -> Dict[str,str]` ("Startup finished in 4.2s (firmware) + … = 13.2s" → firmware/loader/kernel/userspace/total)
- `parse_blame(text, limit=8) -> List[Tuple[str,str]]`
- `boot_info() -> dict` (graceful `{}` when systemd-analyze missing)
Tests: parsing fixtures inline; regex rejects `evil;rm.service` and bad actions. Commit.

### Task 5: GUI pages (gui.py + runtime test update)
- Sidebar grows to 9: `deepclean` ("Deep Clean", broom icon `user-trash-symbolic`, tile-orange) and `services` ("Services", `system-run-symbolic`, tile-purple); Optimize→tile-pink, Customize→tile-teal, Backup→tile-slate, Logs→tile-slate (reuse).
- `_build_deepclean_page()`: card listing scanned items as rows (icon + label + detail + size chip + CheckButton), total-size label, "Scan Now" + "Clean Selected" (primary) buttons; scan via `submit(deepclean.scan_cleanable, done=self._apply_clean_scan)`; clean builds `utils.run_actions` steps (`clean_apt_cache`/`vacuum_journal` for root items, `clean_user_paths` batch for user items) — reuses simulate gating + busy widgets.
- `_build_services_page()`: "Boot time" card (total + phases line + top-blame rows) and services card (search entry + `Gtk.ListBox` rows: unit name + description dim + active chip + unit-state badge; per-row Start/Stop/Enable/Disable handled via selected row + bottom buttons wired to `set_service_state`, then re-list).
- Update `tests/test_gui_runtime.py` page-count assertion 7 → 9 (and fire the two new page-build handlers).
Verify: `make lint && make test`; GUI smoke run; commit.

### Task 6: Final verification & docs
Full `make lint && make test`, GUI 15s smoke, README feature table + screenshots section updated, CHANGELOG final pass, commit.

**Not changing:** simulate gating design, task runner, existing handler names, `.venv` (stale).
