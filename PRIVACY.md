# Privacy policy for the Preen desktop app

**Last updated: 2026-10-28**

This policy describes the current Preen desktop application in this repository.
It does not describe a future website or change the policies of GitHub, your
Linux distribution, package repositories or other programs. Features and
behaviour can differ in older releases.

## Data Preen reads

To display its pages and perform requested actions, Preen reads information
such as the operating system, resource usage, installed applications, services,
startup entries, configuration files and available system tools. It displays
relevant results locally. Configuration paths, package names and command output
may identify your device, user account or installed software.

The current app has **no built-in telemetry, analytics, account system or
crash-report upload**. It does not automatically send its logs or system
inventory to the Preen maintainers. This is not a promise that all operations
are offline: external tools and services can communicate independently.

## Files and retention on your device

| Data | Where and how long it stays |
|---|---|
| Preen preferences | `~/.config/preen/settings.json`, until you change or remove it. On loading, an existing legacy `~/.config/zorin-optimizer` directory may be moved to `~/.config/preen` if the new directory does not already exist. |
| App logs | Up to 4,000 recent lines are kept in memory. **Save Log** writes the retained, unfiltered log to the path you choose; that file remains until you remove it. Other system tools can keep their own logs. |
| Config exports | Archives are written to the location you choose and remain there until removed. The export can include regular files from `~/.config`, including private settings, tokens or credentials; some named caches and links are skipped. Preen does not encrypt the archive. |
| Icon themes and backups | When you install a theme, it is placed under `~/.icons`; a replaced theme may be kept under `~/.icons/.preen-backups/`. |
| Other changes | Requested operations can create or modify startup entries, desktop settings, Timeshift snapshots, package-manager records, system logs and other files controlled by your system or external tools. |

Simulate previews supported maintenance changes, but it is not a no-write
sandbox. Read-only commands still run, preferences and a chosen log can be
saved, and legacy settings migration can occur while Simulate is enabled.

Uninstalling Preen does not automatically remove every setting, export, saved
log, icon backup, system record or snapshot. You control these local copies:
inspect their locations and delete only the items you no longer need. Removing
`~/.config/preen` resets Preen's preferences; do not delete all of `~/.config`
or other applications' files as a substitute. Secure backup and deletion depend
on your device, filesystem and backup software.

## Network and third parties

When you choose relevant actions, APT and Flatpak can contact your configured
repositories. Preen may ask Flatpak to set up the Flathub remote when installing
Flatpak apps. Your distribution, repositories, Flathub, DNS provider, network
operator and other external tools may receive information such as your IP
address and requested packages under their own policies. The AppImage build
script may download `appimagetool` if it is not already available.

If you visit this project's GitHub repository, download releases or open an
issue, GitHub processes information under the
[GitHub privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement).
Public issues, comments and attachments are visible to others. The maintainers
may receive information you choose to submit there; do not post secrets.

## Your choices and questions

- Review and redact logs, doctor reports, screenshots and issue attachments
  before sharing. A saved log contains the retained log, not only filtered lines.
- Treat configuration archives and snapshots as sensitive. Store them in a
  protected location and use separate encryption if you need it.
- Decide which optional tools, repositories and maintenance actions to use.
- For a privacy question, see the [maintainer profile](https://github.com/mdadeel)
  or open a [non-sensitive issue](https://github.com/mdadeel/Preen/issues). Do
  not post personal information or secrets in a public request.

This description will be updated when the app's data practices change. A future
website will need its own accurate disclosure based on the hosting and services
actually chosen; see the [website plan](docs/WEBSITE_PLAN.md).
