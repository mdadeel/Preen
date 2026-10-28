# Preen product roadmap

This is a proposed plan, not a list of features already implemented. Build on
Preen's existing Python/GTK 3 application, nine pages, FIFO worker queue,
package protections, polkit handling, simulation and diagnostic logs. Keep
optional integrations optional; do not require a new daemon or large
framework for the first releases.

## 1. A more polished, macOS-inspired interface

The aim is the restraint and clarity of a system settings app, not a copy of
Apple artwork or controls. Use native GTK controls, Preen's existing dark
tokens and an 8 px spacing rhythm. Retain readable labels, visible state and
keyboard access rather than relying on colour or icon shape alone.

| Phase | Work | Acceptance criteria |
|---|---|---|
| Foundation | Define semantic text, surface, border, accent and state colours; audit dark/light contrast and disabled, hover, focus and selected states. Use one icon and typography scale. | Normal text and action labels meet 4.5:1 against their actual backgrounds; focus, switches and selection remain visible without colour alone. No system theme is changed by Preen's appearance selector. |
| Navigation and layout | Refine sidebar groups, compact toolbar, card spacing and page headings. Make dense lists and action bars adapt to narrow windows without hiding actions. | All nine pages work at 720×480, 1180×780 and 1600×900, including text scaling; tab order, search, selection and scrolling remain usable. |
| Detail and feedback | Use consistent symbols, actual installed app icons and honest offline fallbacks. Refine empty, loading, partial-failure and confirmation states; preserve full diagnostic logs. | No missing-image glyphs or fabricated status; Save/Select/toggle controls have clear names and states. Screen-reader names, keyboard focus and light/dark states are checked on GTK. |
| Desktop QA | Review on supported GNOME/X11 and Wayland, multiple icon themes, HiDPI and a screen reader. Capture representative screenshots and fix real clipping or contrast issues. | Manual checklist and screenshots cover each page and common dialogs; results and untested environments are recorded. Existing simulated and real operation safeguards still pass. |

## 2. Folder organizer

### User flow

1. Choose a folder with a native folder picker; suggest Downloads but never
   scan or change it without the user's selection. Display the resolved path,
   filesystem and scope before scanning.
2. Select a local rule set: extension groups (documents, pictures, audio,
   video, archives, code and so on), optional user rules, or a **preview-only**
   similarity view based on name/date/size. Use case-insensitive matching and
   recognise compound extensions such as `.tar.gz`. Unknown files remain in
   place unless the user opts into an Other group.
3. Show a per-file plan with source, proposed destination, rule, conflicts,
   skipped items and real counts. Allow excluding individual files or rules;
   provide a dry run with no writes. Nothing moves on scan or preview.
4. After explicit confirmation, apply the exact plan in the existing worker
   queue, with honest completed/skipped/failed counts, cancellation between
   files and a detailed log. Offer an undo summary after completion.

### Safety contract for the first release

- Start with non-recursive, same-filesystem moves of regular files owned and
  writable by the user. Do not require root; do not follow symlinks, special
  files, mount points or symlinked destination components. Hidden files,
  subfolders, hard links and unsupported filesystems are skipped by default.
  Guard system locations, home/config roots and other high-risk folders with
  explicit refusal or a separately reviewed advanced flow.
- Restrict destinations to checked subdirectories within the chosen folder.
  Exclude organizer-created destinations from scans. Resolve paths safely and
  revalidate source identity/metadata and destination after preview to catch
  changes and symlink races.
- Never overwrite a destination. Default to **skip on collision**; an explicit
  deterministic rename option can be previewed. Use no-replace filesystem
  operations and fail safely if they are unavailable. Cross-filesystem copies,
  removable drives and network shares are deferred until copy, fsync,
  verification and recovery semantics are implemented and tested.
- Write a private, durable operation journal recording only the actual moves
  and enough identity information to check them. Undo only an unchanged file
  whose original path is still free; never overwrite or delete a newer file.
  Report conflicts and partial failures individually, and retain the journal
  for recovery after cancellation or a crash.
- Similarity is a suggestion, not a reason to delete or silently consolidate
  files. Optional exact-duplicate detection must hash locally and compare
  content; near-duplicate or content/AI classification is a later, opt-in
  project with clear privacy and resource limits. No background scans or
  network uploads by default.
- Simulate must not create folders, move files or write an operation journal.
  Tests use disposable directories and cover collisions, stale previews,
  permission failures, symlinks, hard links, changed files, partial runs,
  cancellation, interrupted journals and undo conflicts. Real filesystem and
  supported-desktop tests are required before shipping.

## 3. Other integrated utilities, in priority order

| Priority | Proposed utility | First useful release and guardrails |
|---|---|---|
| 1 | **Storage explorer and duplicate review** | Per-folder disk usage with permission/mount warnings; local exact-hash duplicate groups with selection and preview. Move to the user's trash only after confirmation, never auto-delete. Complements Deep Clean instead of duplicating it. |
| 2 | **Unified update overview** | Read actual APT/Flatpak update availability and errors in one place, with per-source refresh. Reuse existing install/update queue, source fallback, confirmations and logs; do not present guessed update counts. |
| 3 | **Flatpak permissions** | Read installed app permissions and clearly distinguish defaults from overrides. Offer only individually reviewed, reversible overrides with explicit confirmation; Flatpak must remain optional. |
| 4 | **Hardware, battery and power insights** | Read battery health/cycles where exposed, temperatures, disks and power-profile capabilities. Show unavailable instead of zero; avoid privileged tuning by default. Extend the existing Dashboard and Optimize pages. |
| 5 | **Network and firewall diagnostics** | Read-only interface, DNS and connectivity checks plus firewall status where tools exist. Any repair or rule change is a separate previewed, reversible, authorized action; no silent network changes. |
| 6 | **Maintenance history and scheduling** | First show actual completed operations, outcomes and saved logs. Only later consider opt-in scheduled, narrowly scoped tasks with clear ownership, disable/remove controls and no always-on daemon by default. |

Reuse existing startup, service, backup and Timeshift integrations instead of
reimplementing them. Validate each proposal against user demand and supported
distro/tool availability before adding dependencies or expanding privileges.

## 4. Delivery order

1. Stabilize the current appearance, icon and scope fixes; complete the real
   desktop/accessibility QA above.
2. Prototype the organizer's scan and dry-run plan without moves; test the
   safety contract and review the journal and filesystem design.
3. Ship same-filesystem moves and conservative undo only after failure and
   recovery tests pass; defer advanced similarity and cross-device work.
4. Add storage insights, then permission/update/network utilities in small,
   independently testable slices. For every slice, document simulation,
   failure states, reversibility and optional system dependencies.
