# Building and publishing releases

Build from a clean checkout of the commit that will be tagged. Keep generated
artifacts out of Git. Use a supported Linux build environment with Git, Python
3.8+, setuptools, wheel, `dpkg-deb`, `sha256sum` and the dependencies listed in
the [user guide](USER_GUIDE.md). Install and verify a trusted x86-64
`appimagetool` AppImage if an AppImage is required.

```bash
# Validate first; tests use fakes rather than modifying the host system.
python3 -m unittest discover -s tests -q
python3 -m preen_tool.app --check-catalog

# Builds into dist/release-<version>/; the destination must be empty.
APPIMAGETOOL=/path/to/trusted/appimagetool-x86_64.AppImage \
  ./packaging/build_release.sh
```

The script checks version consistency and source-tree identity, then creates:

- `preen-<version>-source.zip`, a source ZIP from the selected Git commit;
- `preen-<version>.tar.gz`, a Python source distribution;
- `preen-<version>-py3-none-any.whl`, a Python wheel;
- `preen_<version>_all.deb`, a Debian package;
- `Preen-<version>-x86_64.AppImage`, when its build and CLI smoke test succeed;
- `SHA256SUMS` for the files actually built.

The Debian package and AppImage use the host's system tools; the AppImage also
requires host Python, GTK 3 and PyGObject. The AppImage builder may download
`appimagetool` without verifying its checksum if `APPIMAGETOOL` is not set;
the tool may also download a runtime that Preen does not verify. For a release,
provide a trusted pre-verified tool and verify its runtime in a controlled build
environment. A successful CLI smoke test is not a live desktop, polkit or
package-manager test.

If the AppImage cannot be built, `./packaging/build_release.sh --skip-appimage`
creates and verifies the other files and explicitly reports the omission. Do
not name a stub or a partial file as an AppImage. The optional environment
variable `PREEN_SOURCE_REF` selects the commit used for the source ZIP; its tree
must match the clean checkout, so a merge commit with identical content can be
used without changing branches.

## Publishing checklist

1. Update `preen_tool/__init__.py`, `pyproject.toml`, `debian/changelog` and
   `CHANGELOG.md` together, and write accurate release notes. Do not move an
   existing tag to make a newer build appear to be an older release.
2. Run the test suite and release builder. In the artifact directory, run
   `sha256sum --check SHA256SUMS`. These checksums detect corruption; they are
   not a cryptographic signature of the publisher.
3. Create a draft GitHub release for the matching tag and exact commit, upload
   the verified files and `SHA256SUMS`, then confirm every filename and size on
   the release page. GitHub generates its own source ZIP and tarball for the tag.
4. Publish only the artifacts that were actually built and checked. State
   missing assets, network restrictions and untested desktop/privileged paths
   in the release notes instead of claiming complete verification.
5. Confirm the release's tag, commit and download links after publishing.

For security, do not share tokens in release notes, logs or command examples.
