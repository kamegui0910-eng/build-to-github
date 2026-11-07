"""Offline checks for the explicit-file publication helper."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "skills/build-to-github/scripts/prepare_publication.py"
SPEC = importlib.util.spec_from_file_location("prepare_publication", SCRIPT)
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.allowlist = self.base / "public.json"
        self.out = self.base / "prepared"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, content=b"public example"):
        file = self.root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)

    def prepare(self, entries, out=None):
        self.allowlist.write_text(json.dumps(entries), encoding="utf-8")
        return publication.freeze(self.root, self.allowlist, out or self.out)

    def assert_rejected(self, entries):
        with self.assertRaises((publication.PublicationError, OSError)):
            self.prepare(entries)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.base.glob(".publication-*")), [])

    def test_snapshot_hashes_exact_bytes_and_only_explicit_files(self):
        content = b"\x00\xff\x10\n"
        self.write("assets/data.bin", content)
        self.write("README.md", "中文\n".encode())
        self.write("unlisted.txt", b"not included")
        result = self.prepare(["README.md", "assets/data.bin"])
        self.assertEqual(result["file_count"], 2)
        row = result["files"][1]
        self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(row["git_blob_sha1"], hashlib.sha1(b"blob 4\0" + content).hexdigest())
        self.assertEqual((self.out / "source/assets/data.bin").read_bytes(), content)
        self.assertFalse((self.out / "source/unlisted.txt").exists())
        self.assertEqual(json.loads((self.out / "manifest.json").read_text(encoding="utf-8")), result)
        with zipfile.ZipFile(self.out / "source.zip") as archive:
            self.assertEqual(archive.namelist(), ["README.md", "assets/data.bin"])
            self.assertEqual(archive.read("assets/data.bin"), content)
            self.assertEqual(archive.getinfo("README.md").date_time, (1980, 1, 1, 0, 0, 0))

    def test_reproducible_independent_of_allowlist_order_and_source_mtime(self):
        self.write("b.txt")
        self.write("a.txt")
        self.prepare(["b.txt", "a.txt"])
        other = self.base / "prepared-second"
        self.prepare(["a.txt", "b.txt"], other)
        self.assertEqual((self.out / "source.zip").read_bytes(), (other / "source.zip").read_bytes())
        self.assertEqual((self.out / "manifest.json").read_bytes(), (other / "manifest.json").read_bytes())

    def test_rejects_absolute_traversal_and_ambiguous_paths(self):
        for entry in ["../private.txt", "/absolute.txt", "C:\\secrets.txt", "a/../b", "./a", "a//b", "a:stream", "a. "]:
            with self.subTest(entry=entry):
                self.assert_rejected([entry])

    def test_rejects_duplicate_and_case_conflicting_entries(self):
        self.write("readme.md")
        self.assert_rejected(["readme.md", "readme.md"])
        self.assert_rejected(["readme.md", "README.md"])

    def test_rejects_directories_missing_files_and_invalid_arrays(self):
        (self.root / "src").mkdir()
        for entries in [["src"], ["missing.txt"], [], {"files": []}, [1]]:
            with self.subTest(entries=entries):
                self.assert_rejected(entries)

    def test_rejects_private_names_but_allows_env_example(self):
        private = [".env", ".env.local", ".git/config", "node_modules/pkg/main.js", ".dev.vars",
                   "Cookies", "cookies.sqlite", "storageState.json", "storage-state.json",
                   "credentials.json", "secrets.encrypted.json", "school-logins.json",
                   "sessions/live.txt", "browser-profiles/live.txt", "private.key"]
        for name in private:
            with self.subTest(name=name):
                self.write(name)
                self.assert_rejected([name])
        self.write(".env.example", b"API_KEY=replace_me\n")
        self.assertEqual(self.prepare([".env.example"])["file_count"], 1)

    def test_rejects_tokens_and_private_keys_without_printing_them(self):
        samples = [b"gh" + b"p_" + b"A" * 36,
                   b"sk-" + b"proj-" + b"B" * 30,
                   b"-----BEGIN " + b"RSA PRIVATE KEY-----"]
        for sample in samples:
            with self.subTest(kind=sample[:2]):
                self.write("source.txt", sample)
                self.assert_rejected(["source.txt"])
                self.allowlist.write_text('["source.txt"]', encoding="utf-8")
                stream = io.StringIO()
                with contextlib.redirect_stderr(stream):
                    code = publication.main(["--root", str(self.root), "--allowlist", str(self.allowlist), "--out", str(self.out)])
                self.assertEqual(code, 2)
                self.assertNotIn(sample.decode(), stream.getvalue())

    def test_rejects_output_inside_root_and_existing_output(self):
        self.write("a.txt")
        with self.assertRaises(publication.PublicationError):
            self.prepare(["a.txt"], self.root / "prepared")
        self.out.mkdir()
        (self.out / "keep.txt").write_text("keep")
        with self.assertRaises(publication.PublicationError):
            self.prepare(["a.txt"])
        self.assertEqual((self.out / "keep.txt").read_text(), "keep")

    def test_validation_failure_after_valid_file_creates_no_snapshot(self):
        self.write("a.txt")
        self.assert_rejected(["a.txt", "missing.txt"])

    def test_write_failure_cleans_output_and_staging(self):
        self.write("a.txt")
        original = Path.rename

        def fail_manifest(path, target):
            if path.name == "manifest.json":
                raise OSError("simulated disk failure")
            return original(path, target)

        with patch.object(Path, "rename", fail_manifest):
            self.assert_rejected(["a.txt"])

    def test_rejects_file_parent_and_root_symlinks(self):
        self.write("a.txt")
        target = self.base / "outside"
        target.mkdir()
        (target / "file.txt").write_text("private")
        try:
            (self.root / "link.txt").symlink_to(target / "file.txt")
            (self.root / "linked").symlink_to(target, target_is_directory=True)
            alias = self.base / "root-alias"
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("Operating system does not permit symlink creation")
        self.assert_rejected(["link.txt"])
        self.assert_rejected(["linked/file.txt"])
        self.allowlist.write_text('["a.txt"]', encoding="utf-8")
        with self.assertRaises(publication.PublicationError):
            publication.freeze(alias, self.allowlist, self.out)


if __name__ == "__main__":
    unittest.main()
