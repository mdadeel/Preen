# 🔥 The Brutal Roast (and the rebuild)

A historical audit of **v0.1.0** (commit `68356a5`), written while fixing it.
This is about the code, not the person who wrote it. Counts and claims below
refer to that review, not necessarily the current release. For present-day
behaviour and test limitations, see the [README](../README.md) and
[functional review](FEATURE_AUDIT.md).

> **Update (2026-10-27):** after the reliability rewrite below, the repo got a
> UX and cleanliness pass — Dashboard landing page, getting-started guide,
> non-modal notifications, spinner, persistent Simulate banner, empty states,
> selection counters, Preferences/Help/About, dependency warnings, plus
> `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `Makefile`, `.editorconfig`,
> `docs/USER_GUIDE.md`, `docs/ARCHITECTURE.md`, a docs index and an `archive/`
> for stale documents. See the [changelog](../CHANGELOG.md).

> **TL;DR:** the app you installed from the `.deb` literally could not start,
> the app you ran from the repo froze on launch, "Simulate" simulated nothing
> for most of the UI, and "Optimize" sometimes deleted your swapfile. It was a
> very pretty GUI wrapped around a bag of unchecked `subprocess` calls.

---

## 1. You shipped a car with no engine — `P0`

`pyproject.toml` declared:

```toml
[tool.setuptools]
packages = ["preen_tool"]
```

That ships `app.py` and `config/*.json`. It does **not** ship
`preen_tool/backend/`. The committed build output proves it:

```
$ unzip -l .pybuild/.../zorin_optimizer-0.1.0-py3-none-any.whl
preen_tool/__init__.py
preen_tool/app.py
preen_tool/config/apps.json
preen_tool/config/presets.json
...                       # ← no backend/, at all
```

`app.py` starts with `from .backend import utils`. So the installed `.deb`
dies with `ModuleNotFoundError` before a single pixel is drawn. The README
cheerfully recommends installing exactly that `.deb`. That's not a bug, that's
the entire product being a 404.

**Fix:** package discovery (`[tool.setuptools.packages.find]`) + `MANIFEST.in`.
`test_built_wheel_contains_the_backend` builds a real wheel and asserts all 8
backend modules, `gui.py`, `cli.py` and both JSON files are inside.

---

## 2. "Simulate" was a decorative switch — `P0`

`run_cmd()` honoured `mutate=True` in dry-run mode. So count how many of the
mutating actions actually passed it:

| Backend | `mutate=True` | What it actually changes |
|---|---:|---|
| `apps.py` | 16 | installs, removals, updates |
| `performance.py` | 4 | swapfile, ZRAM |
| `system.py` | 2 | cleanup |
| `backup.py` | 1 | Timeshift |
| **`ui_customization.py`** | **0** | **gsettings theme, tar extraction, gtk.css writes** |

Plus `set_animations()` (gsettings), `set_power_profile()` (powerprofilesctl),
`set_startup_app()` (writes `.desktop` files), `export_configs()` /
`import_configs()` (writes archives and overwrites `~/.config`) — none were
gated. A user who turned on "Safety: Simulate Mode" and clicked through the UI
would still get a new theme, a rewritten `gtk.css`, an extracted icon pack and
an overwritten config directory. The safety feature was a sticker.

**Historical fix:** the listed maintenance actions were gated and a regression
test checks selected operations with Simulate on using a fake system. Simulate
is not a no-write sandbox: preferences, saved logs and legacy-settings migration
are exceptions. See the current [architecture](ARCHITECTURE.md#simulate-contract).

---

## 3. Two buttons crashed on click, guaranteed — `P1`

```python
btn_snap.connect("clicked", lambda _b: self._run_async(
    __import__('preen_tool.backend.backup', fromlist=['']).backup.timeshift_snapshot))
```

`__import__(...)` returns the module `preen_tool.backend.backup`. That
module has no attribute `backup`. `AttributeError` at click time, in the main
thread. Both "Create Timeshift Snapshot" and "Open Timeshift GUI" were dead on
arrival, and there were **two** of these lines. Meanwhile the file imports
`json`, `os` and `Dict` at the top for no reason. One wonders who reviewed it.

**Fix:** `from .backend import backup` at the top, normal function references.
GUI smoke test asserts `on_snapshot` / `on_open_timeshift` exist.

---

## 4. The async runner re-ran mutating commands — `P1`

```python
try:
    func(*args, log=self.log_buf)
except TypeError:
    result = func(*args)          # ← run it a SECOND time
```

If a backend function raised `TypeError` **after** doing part of its work —
a bad dict key halfway through an install loop, a GTK quirk, anything — this
handler calmly executed the whole mutating function again. An `apt-get remove`
that half-succeeded gets a second helping. This is the kind of bug that earns
a CVE-shaped nickname.

It also masked real `TypeError`s, and it existed only because some callables
accepted `log` and some didn't — no signature inspection anywhere.

**Fix:** `utils.accepts_log()` uses `inspect.signature`; no retries, one
`try/except` with a full traceback. `test_run_actions_never_reexecutes_on_internal_typeerror`
proves a function that raises `TypeError` internally runs exactly once.

---

## 5. GTK off the main thread, and 60 subprocesses on it — `P1`

`_install_apps()`, `_update_all()`, `_update_selected()`, `_uninstall_apps()`
all ended with `self.on_refresh_status(None)` — called **from the worker
thread**, which then called `lbl.set_text()` on ~45 `Gtk.Label`s. GTK is not
thread-safe. That's a crash lottery.

Meanwhile `on_refresh_status()` ran during `__init__` on the UI thread and
`get_status_label_map()` spawned **one `flatpak list` and one `dpkg-query` per
catalogue entry** — roughly 60 processes before the window finished drawing.
And `on_scan_installed` built thousands of `Gtk.ListBoxRow`s inside a single
`idle_add`. Congratulations, the "optimizer" is the thing freezing your
desktop.

**Fix:** two queries total (`flatpak list` + one `dpkg-query -W` for all
packages), cached and invalidated after mutations. All widget updates happen
via `GLib.idle_add`. Startup scans are chained through a serialised task runner
that also blocks double-clicks. `test_status_detection_uses_two_queries_not_forty`
asserts **exactly 2** subprocesses.

---

## 6. Exit codes were decorative — `P1`

Every single `run_cmd(...)` return value was thrown away. `apt-get install`
could exit 100 because the package doesn't exist, and the UI would log the
command with a happy little prefix and carry on. There was no `Outcome`, no
error dialog, no failure state, no distinction between "installed" and
"apt screamed into stderr". The Logs page was a command echo chamber.

**Fix:** `CommandResult`, `Report`, `Outcome`. Every command logs `$ argv`,
exit code and stderr tail; operations aggregate failures and the GUI shows a
red status + dialog with the details. `test_run_cmd_reports_failures` covers it.

---

## 7. Your install detection lied — `P1`

```python
code, out, _ = run_cmd(["dpkg-query", "-W", "-f=${Status}", pkg])
return code == 0 and "installed" in out
```

`dpkg-query` returns **0** for packages it knows about but which are purged,
with `${Status}` = `purge ok not-installed`. Contains the substring
`"installed"`. So purged packages were reported as installed, forever. Also
`dpkg -S` output for multiarch (`pkg:amd64: /path`) was parsed by splitting on
the first colon, producing garbage package names and a "Manage Apps" list that
could offer to remove `amd64`.

**Fix:** parse the third status field exactly (`== "installed"`), collect all
packages in one query, include `${binary:Package}` for multiarch, and parse
`dpkg -S` from the right. Tests cover both.

---

## 8. The catalogue was fan fiction — `P1`

Verified all 37 Flatpak IDs against the `flathub` GitHub org:

| Entry in `apps.json` | Reality |
|---|---|
| `org.freedesktop.Sdk.Extension.node18` | an **SDK extension**, not an app, and Node 18 is EOL |
| `org.freedesktop.Platform.VulkanLayer.MangoHud` | a **runtime extension**, not an app |
| `com.github.oguzhaninan.Stacer` | no such Flathub repo |
| `com.github.costales.gufw` | no such Flathub repo |
| `com.jetbrains.Toolbox` | no such Flathub repo |

Plus `presets.json` pointed "Minimalist Pack" at Stacer, and "Developer Pack"
at Node 18 the SDK extension. Selecting those and pressing Install was a
reliable way to get `error: No remote refs found`. That is the core feature of
the app. Nice.

**Fix:** removed all five, replaced with real apps (verified against the
Flathub repository list), added APT alternatives for 20+ entries, added
`note` tooltips, and `validate_catalog()` + `--check-catalog` so this can
never silently rot again.

---

## 9. "Run Optimization" was a swapfile assassin — `P1 / data loss`

```python
if opts.get("swap"):  perf_backend.enable_swapfile(2)
else:                 perf_backend.disable_swapfile()
if opts.get("zram"):  perf_backend.enable_zram()
else:                 perf_backend.disable_zram()
```

Unconditionally. Click "Run Optimization" with everything unticked and it
runs `pkexec bash -c "swapoff /swapfile; sed -i /etc/fstab; rm -f /swapfile"`.
Your pre-existing swapfile: gone. Same for the ZRAM config. And
`enable_swapfile()` bailed out if *any* swap was active (`if out.strip()`), so
having ZRAM made the swap checkbox a no-op. `enable_zram()` then tried
`systemctl start /dev/zram0` — that's a device node, not a systemd unit. It
was wearing `|| true` as a disguise so you'd never know it failed.

**Fix:** diff-based optimisation — only settings that changed are applied.
`disable_swapfile()` refuses to run unless the file exists, `enable_swapfile()`
has a `dd` fallback, fstab writes are newline-safe, and the ZRAM unit is
`systemd-zram-setup@zram0.service`. Tests assert no `pkexec` is spawned when
there is nothing to disable.

---

## 10. Two tar extraction holes — `P1 / security`

- `install_icon_pack()`: bare `tarfile.extractall(dest)` on a user-supplied
  archive → `../../.bashrc` writes anywhere in `$HOME`. It then picked the icon
  theme by **directory mtime**, so an unrelated folder you touched yesterday
  could become your icon theme.
- `import_configs()`: had a `commonpath` check, but symlink/hardlink members
  were still passed to `extractall`, and Python < 3.12 follows them. A crafted
  "backup" could escape `~/.config`.

**Fix:** `utils.safe_tar_members()` rejects absolute paths, `..`, symlinks,
hardlinks, devices and setuid bits for **both** paths. Icon themes are detected
by `index.theme` inside a temp directory, then copied. Config import refuses
the whole archive if it contains unsafe entries. Tests build genuinely
malicious tarballs and assert nothing escapes.

---

## 11. Everything else that made me sigh — `P2`

- `app.run(None)` — `Gtk.Application.run` wants argv. Now `app.run([argv0])`.
- `application_id="org.example.zorinoptimizer"` — an `example` domain, in a
  shipped desktop app. Now `io.github.mdadeel.ZorinOptimizer`.
- `StartupWMClass=Zorin Optimizer` — matched nothing.
- `gsettings` theme code did `current_theme + "-dark"` and set it **without
  checking the theme exists**. Now only installed themes are applied.
- `powerprofilesctl set` accepted any string from the combo and ignored failure.
- Startup toggles used `Hidden=true` only (GNOME wants
  `X-GNOME-Autostart-enabled`), listed system **and** user duplicates, and
  appended keys to the end of the file — inside whatever group came last.
  Now both keys are written atomically inside `[Desktop Entry]`.
- Dashboard printed `Linux 6.8.0-…` as the "OS". Now reads
  `/etc/os-release` `PRETTY_NAME`, and works without psutil.
- `env=env` in `run_cmd` **replaced** the entire environment instead of
  merging, so any command using it lost `PATH`, `HOME`, `DISPLAY`.
- `pkexec` was hardcoded as `argv[0]` in ~10 places while `use_pkexec=True`
  existed. Now normalised once: one pkexec, none when root, clear error when
  polkit is absent.
- The earlier `docs/code_review.md` claimed the presets were broken; they were
  already fixed. That historical audit is not included in the current checkout.
- The repo committed `build/`, `.pybuild/`, `*.pyc`, `zorin_optimizer.egg-info/`,
  a complete staged `debian/zorin-optimizer/` tree, **and a `.venv/` whose
  `pyvenv.cfg` contains `/home/moft/Music/zorin-optimizer/.venv`**. Someone
  else's home directory, version-controlled, as a build artefact. Deleted and
  gitignored.
- There were **zero tests**. Zero. For a tool that runs `apt-get remove -y`
  and rewrites `/etc/fstab`.

---

## ✅ What v0.2.0 changes

| Area | Change |
|---|---|
| Packaging | auto package discovery, `MANIFEST.in`, `.gitignore`, cleaned tracked build junk, version 0.2.0, `polkitd \| policykit-1` |
| Core | new `utils.py` result/report types, `run_actions`, safe tar filtering, `parse_desktop_file`, env merging, one-polkit normalisation |
| Apps | validated catalogue, 2-query detection, batching, source fallback, essential-package guard, regex-validated scanner rows |
| GUI | new `gui.py` with serialised task runner, all UI updates on the main thread, searchable lists, confirmations, error dialogs, live status, saveable log |
| CLI | `app.py` is GTK-free; `--doctor`, `--doctor --json`, `--check-catalog`, `--version`, `--simulate` |
| Safety | Selected maintenance actions are gated by Simulate; archive traversal checks added. See the current [Simulate limitations](ARCHITECTURE.md#simulate-contract). |
| UX | Dashboard landing page with a 3-step guide and tool-availability panel; dismissible info/warning/error banner instead of modal spam; progress spinner; persistent Simulate banner; search + empty states; Select all / Clear; selection counters; Preferences (persistent, validated), Help and About; primary/destructive button styling. |
| Repository | `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `Makefile`, `.editorconfig`, docs index, `USER_GUIDE.md`, `ARCHITECTURE.md`; historical docs moved to `docs/archive/`; generated build output gitignored. |
| Tests | 36 tests (backend, settings, packaging, CLI, GUI construction + all handlers) with a fake Linux userspace and fake GTK; runs in ~1 s with no root, no display, no network. A ready-to-use GitHub Actions workflow is included as [`docs/ci-workflow.yml.example`](ci-workflow.yml.example) for Python 3.9/3.11/3.12 — copy it to `.github/workflows/ci.yml` to enable CI. |

## 🔍 Verify it yourself

```bash
make test      # 36 regression tests
make doctor    # installation + dependency report
make check     # catalogue validation
make wheel     # builds a wheel, then: unzip -l dist/*.whl
make help      # everything else
```

Then, on a real Zorin desktop, launch with `--simulate` and click everything.
The Logs page will show exactly what *would* have run — and your `/swapfile`
will still be there.
