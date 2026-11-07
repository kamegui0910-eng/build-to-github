#!/usr/bin/env python3
"""Freeze an explicit public file list; no upload or authentication.

Usage: python prepare_publication.py --root PROJECT --allowlist public-files.json --out NEW_DIR
The allowlist file must contain a JSON array of relative file paths. The output
parent must exist; NEW_DIR must not exist and must be outside PROJECT. Filename
and limited token checks do not prove that files contain no private information.
Run against a quiet, trusted local tree; this is not an adversarial-filesystem sandbox.
"""

import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile


class PublicationError(ValueError):
    pass


PRIVATE_DIRECTORIES = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".wrangler",
    ".sites-runtime", ".cache", ".sessions", "sessions", "browser-profiles",
    "user-data", "userdata", ".aws", ".ssh",
}
PRIVATE_NAMES = {
    "credentials", "credentials.json", "credentials.yaml", "credentials.yml",
    "secrets.json", "secrets.encrypted.json", "school-logins.json", "runtime.json",
    "login data", "web data", "history", "local state", "preferences",
    "id_rsa", "id_ed25519", "id_ecdsa", ".npmrc", ".pypirc", ".netrc",
}
TOKEN_PATTERNS = [
    re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}\b"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
]


def reject_links(path):
    """Include ancestors so an in-root link cannot disguise a private source."""
    for item in reversed((path, *path.parents)):
        if item.is_symlink():
            raise PublicationError("Symbolic links are not allowed")
        if item.exists():
            attributes = getattr(item.lstat(), "st_file_attributes", 0)
            if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PublicationError("Filesystem reparse points are not allowed")


def public_relative(raw):
    if not isinstance(raw, str) or not raw or any(ord(c) < 32 for c in raw):
        raise PublicationError("Each allowlist entry must be a nonempty relative file path")
    name = raw.replace("\\", "/")
    parts = name.split("/")
    if ntpath.splitdrive(raw)[0] or name.startswith("/") or any(
        p in ("", ".", "..") or ":" in p or p.rstrip(" .") != p for p in parts
    ):
        raise PublicationError("Absolute, traversal or ambiguous paths are not allowed")
    for part in parts:
        lower = part.casefold()
        compact = re.sub(r"[._ -]", "", lower)
        example = lower.endswith(".example")
        if (lower in PRIVATE_DIRECTORIES or lower in PRIVATE_NAMES
                or lower.startswith("cookies") or compact.startswith("storagestate")
                or ((lower.startswith(".env") or lower.startswith(".dev.vars")) and not example)
                or lower.endswith((".p12", ".pfx", ".key", ".keystore"))):
            raise PublicationError("An allowlist entry has a private/runtime filename")
    return name


def freeze(root, allowlist, out):
    root = Path(os.path.abspath(root))
    out = Path(os.path.abspath(out))
    reject_links(root)
    reject_links(out)
    if not root.is_dir():
        raise PublicationError("Source root must be an existing directory")
    root = root.resolve()
    out = out.resolve()
    if out == root or root in out.parents:
        raise PublicationError("Output must be outside the source root")
    if out.exists() or not out.parent.is_dir():
        raise PublicationError("Output must not exist and its parent must be an existing directory")
    try:
        entries = json.loads(Path(allowlist).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        raise PublicationError("Allowlist must be a readable JSON array file") from None
    if not isinstance(entries, list) or not entries:
        raise PublicationError("Allowlist must be a nonempty JSON array of explicit files")
    payloads = {}
    identities = set()
    for raw in entries:
        name = public_relative(raw)
        identity = unicodedata.normalize("NFC", name).casefold()
        if identity in identities:
            raise PublicationError("Duplicate or case-conflicting allowlist entries")
        identities.add(identity)
        source = root.joinpath(*name.split("/"))
        reject_links(source)
        if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
            raise PublicationError("Every allowlist entry must be an existing regular file")
        if root not in source.resolve().parents:
            raise PublicationError("Source escaped its root")
        content = source.read_bytes()
        if any(pattern.search(content) for pattern in TOKEN_PATTERNS):
            raise PublicationError("Possible credential detected; no content is shown")
        payloads[name] = content

    # Freeze the validated bytes, without reading the live source a second time.
    files = []
    for name, content in sorted(payloads.items()):
        files.append({"path": name, "bytes": len(content),
                      "sha256": hashlib.sha256(content).hexdigest(),
                      "git_blob_sha1": hashlib.sha1(
                          b"blob " + str(len(content)).encode("ascii") + b"\0" + content
                      ).hexdigest()})
    manifest = {"version": 1, "source": "source", "archive": "source.zip",
                "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
                "checks": ["explicit files", "no links or private runtime filenames",
                           "limited credential patterns"],
                "limitations": "These checks do not prove the absence of secrets or personal data. Review the exact snapshot before publishing.",
                "files": files}
    created_out = False
    with tempfile.TemporaryDirectory(prefix=".publication-", dir=out.parent) as temporary:
        stage = Path(temporary)
        source_snapshot = stage / "source"
        source_snapshot.mkdir()
        with zipfile.ZipFile(stage / "source.zip", "w", compression=zipfile.ZIP_STORED) as archive:
            for name, content in sorted(payloads.items()):
                destination = source_snapshot.joinpath(*name.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        manifest["archive_sha256"] = hashlib.sha256((stage / "source.zip").read_bytes()).hexdigest()
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        try:
            out.mkdir()  # Exclusive: never replace an existing output, even if empty.
            created_out = True
            for name in ("source", "source.zip", "manifest.json"):
                (stage / name).rename(out / name)
        except Exception:
            if created_out:
                shutil.rmtree(out)
            raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--allowlist", required=True, help="Path to a JSON array of relative file paths")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = freeze(args.root, args.allowlist, args.out)
    except (PublicationError, OSError, zipfile.BadZipFile):
        print("Publication preflight failed. Check explicit paths, private filenames, credentials and output location. No source content is printed.", file=sys.stderr)
        return 2
    print(json.dumps({"prepared": True, "file_count": manifest["file_count"],
                      "archive_sha256": manifest["archive_sha256"],
                      "review_required": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
