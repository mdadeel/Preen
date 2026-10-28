"""Regression checks for documentation links, legal notices and packaging."""
from __future__ import annotations

import re
import struct
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
import zlib


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "CODE_OF_CONDUCT.md",
    "PRIVACY.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md",
    "docs/README.md", "docs/USER_GUIDE.md", "docs/ARCHITECTURE.md",
    "docs/FEATURE_AUDIT.md", "docs/PRODUCT_ROADMAP.md", "docs/WEBSITE_PLAN.md",
    "docs/RELEASES.md",
)
LINK = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def heading_ids(text):
    """Generate GitHub-style IDs for the headings used by these documents."""
    used = {}
    identifiers = set()
    for heading in HEADING.findall(text):
        heading = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", heading).lower()
        base = "".join(c if c != " " else "-" for c in heading
                       if c.isalnum() or c in "-_ ")
        count = used.get(base, 0)
        used[base] = count + 1
        identifiers.add(base if count == 0 else "{}-{}".format(base, count))
    return identifiers


class DocumentationTests(unittest.TestCase):
    def assert_local_links_exist(self, root):
        for name in DOCUMENTS:
            document = root / name
            self.assertTrue(document.is_file(), "Missing document: " + str(document))
            for target in LINK.findall(document.read_text(encoding="utf-8")):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
                    continue
                path = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
                with self.subTest(document=name, target=target):
                    self.assertTrue(path.is_file(), "Missing relative link: " + str(path))
                    if parsed.fragment and path.suffix.lower() == ".md":
                        self.assertIn(unquote(parsed.fragment),
                                      heading_ids(path.read_text(encoding="utf-8")))

    def test_relative_links_and_anchors_resolve(self):
        self.assert_local_links_exist(ROOT)

    def test_readme_screenshots_are_valid_pngs_with_descriptive_alt_text(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        images = re.findall(r"!\[([^]]+)\]\((docs/images/[^)]+\.png)\)", readme)
        paths = {path for _, path in images}
        self.assertTrue({"docs/images/preen-dashboard.png",
                         "docs/images/preen-manage-apps.png"}.issubset(paths))
        self.assertEqual(len(paths), len(images))
        for alt, name in images:
            with self.subTest(image=name):
                self.assertGreaterEqual(len(alt.split()), 6)
                data = (ROOT / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                offset, seen_end, pixels = 8, False, []
                width = height = 0
                while offset < len(data):
                    self.assertLessEqual(offset + 12, len(data))
                    length = struct.unpack_from(">I", data, offset)[0]
                    kind = data[offset + 4:offset + 8]
                    self.assertNotIn(kind, (b"tEXt", b"zTXt", b"iTXt", b"eXIf"),
                                     "Remove screenshot metadata before publishing")
                    end = offset + 8 + length
                    self.assertLessEqual(end + 4, len(data))
                    chunk = data[offset + 8:end]
                    crc = struct.unpack_from(">I", data, end)[0]
                    self.assertEqual(zlib.crc32(kind + chunk) & 0xffffffff, crc)
                    if kind == b"IHDR":
                        width, height = struct.unpack_from(">II", chunk)
                    elif kind == b"IDAT":
                        pixels.append(chunk)
                    elif kind == b"IEND":
                        seen_end = True
                        self.assertEqual(end + 4, len(data))
                        break
                    offset = end + 4
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertTrue(seen_end and pixels)
                self.assertTrue(zlib.decompress(b"".join(pixels)))

    def test_staged_package_documents_keep_links_and_licenses(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "preen-docs"
            subprocess.run(["bash", str(ROOT / "packaging/stage_docs.sh"), str(destination)],
                           cwd=ROOT, check=True, capture_output=True, text=True)
            self.assert_local_links_exist(destination)
            for name in ("LICENSE", "docs/images/preen-dashboard.png",
                         "docs/images/preen-manage-apps.png",
                         "preen_tool/assets/brand/LICENSE.simple-icons.md"):
                self.assertEqual((destination / name).read_bytes(), (ROOT / name).read_bytes())

    def test_debian_copyright_keeps_the_complete_mit_grant(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2025-2026 Zorin Optimizer contributors", license_text)
        self.assertIn("Copyright (c) 2026 Preen contributors", license_text)
        notice = (ROOT / "debian/copyright").read_text(encoding="utf-8")
        self.assertIn(license_text, notice)
        self.assertIn("Simple Icons", notice)
        self.assertIn("CC0 1.0", notice)

    def test_source_archive_contains_documentation_and_build_helpers(self):
        try:
            import setuptools.build_meta as build_meta
        except ImportError:
            self.skipTest("setuptools build backend not installed")
        with tempfile.TemporaryDirectory() as tmp:
            name = build_meta.build_sdist(tmp)
            with tarfile.open(Path(tmp) / name, "r:gz") as archive:
                members = archive.getmembers()
                source_docs = {path.relative_to(ROOT).as_posix()
                               for path in (ROOT / "docs").rglob("*")
                               if path.is_file() and path.suffix in {".md", ".png"}}
                archived_docs = {m.name.partition("/")[2] for m in members
                                 if m.isfile() and m.name.partition("/")[2].startswith("docs/")}
                self.assertTrue(source_docs.issubset(archived_docs))
                for name in archived_docs:
                    self.assertTrue((ROOT / name).is_file(), "Stale archive document: " + name)
                for expected in ("README.md", "LICENSE", "PRIVACY.md", "SECURITY.md",
                                 "THIRD_PARTY_NOTICES.md", "CODE_OF_CONDUCT.md",
                                 "docs/WEBSITE_PLAN.md", "docs/images/preen-dashboard.png",
                                 "docs/images/preen-manage-apps.png", "docs/RELEASES.md",
                                 "debian/copyright", "packaging/stage_docs.sh",
                                 "packaging/build_deb.sh", "packaging/build_release.sh"):
                    with self.subTest(path=expected):
                        matching = [m for m in members
                                    if m.name.partition("/")[2] == expected]
                        self.assertEqual(len(matching), 1, expected)
                        if expected.startswith("packaging/"):
                            self.assertTrue(matching[0].mode & 0o111, expected)


if __name__ == "__main__":
    unittest.main()
