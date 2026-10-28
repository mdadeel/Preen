# Security policy

## Before changing your system

Preen invokes existing Linux tools and some operations can delete files, remove
packages, change services or alter system configuration. Keep backups, review
the target and use a disposable test system when possible. Run Preen as your
normal user; supported privileged operations request authorization via polkit.
Never share a password, access token or private configuration in a report.

Turn on **Simulate** to preview supported maintenance actions and inspect Logs
before making a real change. Simulate is not a complete no-write sandbox:
read-only checks still run, saving preferences or logs can write files, and
legacy settings migration may occur. A simulated command is not a complete
preview of package-manager dependency changes. Direct app-uninstall protection
covers a defined set of essential APT package names; APT autoremove and
indirect dependencies can affect other packages. Size estimates are not
guarantees, and backup archives are not encrypted by Preen. These measures
reduce risk; they do not replace review or a usable backup.

## Reporting a vulnerability

Please do **not** publish exploit details, credentials or private data in a
public issue. GitHub private vulnerability reporting for this repository was
disabled when this policy was updated on 2026-10-28. If the repository later
shows a **Report a vulnerability** option on its Security tab, use that private
channel.

Otherwise, check the [maintainer's GitHub profile](https://github.com/mdadeel)
for an available private contact method. If none is listed, open a
[minimal public issue](https://github.com/mdadeel/Preen/issues/new) asking how
to establish a private channel; include no exploit, secret or identifying data.
Once a private channel is agreed, share the affected version or commit,
environment, reproduction steps, potential impact and any relevant redacted
logs. Do not test against systems or accounts without permission.

There is no published response-time guarantee or formal supported-version
schedule. Older releases may not include fixes present on the default branch;
consult the [changelog](CHANGELOG.md) and verify the exact release or commit you
run. Maintainers can enable GitHub private vulnerability reporting to make
future confidential reports easier.

## Handling diagnostics

Doctor reports, logs, screenshots and exported configuration archives can
contain usernames, absolute paths, installed apps, tokens or other private data.
Inspect and redact them before sharing, and send only what is necessary. See
the [privacy policy](PRIVACY.md) for storage and retention details.
