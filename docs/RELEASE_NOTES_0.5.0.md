# Preen 0.5.0

Preen is an open-source GTK 3 utility for Linux app management, cleanup,
services, system settings and configuration backups. This release contains the
post-0.4.0 interface, reliability and documentation updates.

## Highlights

- A refreshed, searchable nine-page interface, with Preen-only light, dark and
  Follow system appearance, improved contrast and bundled offline app marks.
- More explicit unavailable and error states, measured cleanup sizes and
  estimates, safer package/service handling and retained diagnostic details.
- Safer configuration restore, guarded swap and ZRAM changes, corrected
  Timeshift listing and improved source-selection and log behaviour.
- Updated README screenshots, privacy and security guidance, license notices
  and a proposed website plan. The proposed folder organizer and website are
  not implemented features.

## Downloads and installation

GitHub provides source ZIP and tarball archives for this release's tag. Check
the assets shown on the release page for any Debian package, Python wheel,
AppImage or checksums; do not assume an unlisted binary is available. If there
is no Debian package, build one from the source checkout:

```bash
./packaging/build_deb.sh
sudo apt install ./dist/preen_0.5.0_all.deb
preen --simulate
```

The AppImage, when available, is x86-64 and uses the host's Python, GTK 3 and
PyGObject. See the [user guide](https://github.com/mdadeel/Preen/blob/v0.5.0/docs/USER_GUIDE.md)
for dependencies and other install options.

## Safety and verification

Simulate previews supported maintenance actions, but it is not a no-write
sandbox: read-only checks run, preferences or saved logs can write files, and
legacy settings may migrate. A simulated command does not predict every
package-manager dependency change. Review destructive operations and keep a
backup. The desktop app has no built-in telemetry; external package repositories
and tools may use the network. See the
[privacy policy](https://github.com/mdadeel/Preen/blob/v0.5.0/PRIVACY.md) and
[security guidance](https://github.com/mdadeel/Preen/blob/v0.5.0/SECURITY.md).

The automated suite uses fake GTK and system commands. It does not establish
visual behaviour on a supported GNOME desktop, real polkit prompts, real package
or service changes, or real Timeshift operations. Check the actual asset list
and verification notes for this release before relying on a binary.
