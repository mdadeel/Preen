# Functional review

This review covers the nine GTK pages and Preferences. It fixes the regressions
listed in the changelog while retaining the existing Python/GTK architecture,
FIFO worker queue, package protections and simulation mode. The checks below
are not a substitute for testing on a supported GNOME desktop.

| Area | Checks performed |
|---|---|
| Dashboard | Metric failure and unavailable states, cleanup confirmation, refresh and navigation handlers. |
| Install Apps | Search and selection, source switching, presets, source fallback, installed-state failures, update/uninstall batching and duplicate prevention. A simulated APT install was exercised through GTK. |
| Manage Apps | Scan warnings, search/selection handlers, protected package rows and backend removal validation. |
| Deep Clean | Size and unavailable-size handling, confirmation, simulation and deletion inside temporary directories, including trash metadata and symlink guards. |
| Optimize System | Action selection and confirmation, animation/power state, all swap sizes, startup entries, swapfile and ZRAM guards. Privileged commands were faked; a failed swap setup was exercised against a temporary file. |
| Services | Running filter, selection and confirmation, all five service command arguments, failed-unit parsing and multi-part boot durations. A restart was previewed through GTK. |
| Backup & Restore | Temporary config archive round trips, unsafe archive/destination rejection, asynchronous inspection, Timeshift parsing, explicit authorization and simulation. Real Timeshift was not run. |
| Customize Look | Modern and legacy fake GNOME settings, repeated light/dark changes, actual GTK CSS palette and Gio change signals, simulation, custom scaling and staged-state preservation, icon archive installation and rounded CSS. |
| Logs | Severity, queued append/filter/clear races, selectable GTK text, saving the unfiltered log, exit details and exception tracebacks. |
| Preferences | Validation and persistence tests; an actual GTK dialog was driven to save all source, refresh, startup-page and switch controls. |

## Test environment and limits

- `python3 -m unittest discover -s tests -q`: 143 tests passed. The catalogue,
  doctor JSON, compilation and `git diff --check` also passed.
- A disposable Broadway display was used with real GTK 3.22 widgets and fake
  Linux commands. Navigation across all nine pages, requested window resizes
  at 720×480, 1180×780 and 1600×900, theme and source toggles, filters,
  preferences and selected simulated actions passed. Resize requests were
  checked programmatically, not by a complete visual inspection.
- That GTK runtime used Python 3.6, below Preen's supported Python 3.8+
  minimum. A temporary project copy removed postponed-annotation imports and
  used the older subprocess spelling solely to run the harness. Its legacy
  PyGObject shutdown was bypassed, so normal shutdown on a supported runtime
  was not established. The runtime emitted fontconfig compatibility warnings.
- No live GNOME, Wayland or X11 session, real desktop theme installation,
  real polkit prompt, package install/removal/update, systemd service change,
  swap/ZRAM modification or Timeshift snapshot/restore was tested. Periodic
  refresh timing and a full visual/accessibility review remain unverified.
  Those checks require an appropriate disposable Linux desktop.
