"""Scan tracked files and historical blobs without a process per file.

The shell entry point owns argument parsing and the history floor, including
the Git-only --baseline/--floor path used by CI and the pre-push hook. This
stdlib-only scanner batches diff-tree and cat-file, keeping names attached to
every blob and checking every merge parent. A content cache stores verdicts,
never file contents; even large blobs are drained in bounded chunks.
"""
from __future__ import annotations

import os
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path


def git(*args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], input=input, capture_output=True, check=True,
    ).stdout


def denied_name(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name == ".env.example":
        return None
    if name == ".env" or fnmatchcase(name, ".env.?*"):
        return "environment file - secrets belong outside the repository"
    if any(fnmatchcase(name, pattern) for pattern in (
        "*.db", "*.db.*", "*.db-shm", "*.db-wal", "*.db-journal", "*.sqlite*",
    )):
        return "database file, sidecar, or backup copy"
    if any(fnmatchcase(name, pattern) for pattern in (
        "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore",
        "id_rsa", "id_ecdsa", "id_ed25519",
    )):
        return "private key or certificate"
    return None


def denied_bytes(prefix: bytes) -> str | None:
    if prefix.startswith(b"SQLite format 3\0"):
        return "SQLite database, whatever the filename says"
    first = prefix.split(b"\n", 1)[0].removesuffix(b"\r")
    if first.startswith(b"-----BEGIN ") and first.endswith((
        b"PRIVATE KEY-----", b"PRIVATE KEY BLOCK-----",
    )):
        return "PEM private key, whatever the filename says"
    return None


class BlobReader:
    def __enter__(self):
        self.process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        return self

    def prefix(self, oid: bytes) -> bytes:
        process = self.process
        process.stdin.write(oid + b"\n")
        process.stdin.flush()
        header = process.stdout.readline().split()
        if len(header) != 3 or header[:2] != [oid, b"blob"]:
            raise RuntimeError(f"cannot read blob {os.fsdecode(oid)}")
        size = int(header[2])
        prefix = process.stdout.read(min(size, 128))
        remaining = size - len(prefix)
        while remaining:
            chunk = process.stdout.read(min(remaining, 64 * 1024))
            if not chunk:
                raise RuntimeError(f"truncated blob {os.fsdecode(oid)}")
            remaining -= len(chunk)
        if process.stdout.read(1) != b"\n":
            raise RuntimeError(f"invalid blob framing for {os.fsdecode(oid)}")
        return prefix

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.process.kill()
        self.process.stdin.close()
        self.process.stdout.close()
        result = self.process.wait()
        if result and exc_type is None:
            raise RuntimeError("git cat-file failed")


def scan(range_args: list[str]) -> int:
    os.chdir(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\n")))
    reported: set[str] = set()

    def report(path: str, reason: str | None) -> None:
        if reason and path not in reported:
            reported.add(path)
            print(f"  {path}\n      {reason}", file=sys.stderr)

    for raw_path in git("ls-files", "-z").split(b"\0"):
        if not raw_path:
            continue
        path = os.fsdecode(raw_path)
        reason = denied_name(path)
        if not reason and Path(path).is_file():
            with open(path, "rb") as stream:
                reason = denied_bytes(stream.read(128))
        report(path, reason)

    if range_args:
        try:
            commits = git("rev-list", *range_args)
        except subprocess.CalledProcessError as exc:
            print("check-tracked-artifacts: cannot resolve the range " + " ".join(range_args), file=sys.stderr)
            print(os.fsdecode(exc.stderr), file=sys.stderr)
            return 2
        # Resolve first and check both Git exits: an invalid range or a failed
        # diff must not look like an empty, successful scan. -z preserves odd
        # filenames; -m includes changes introduced only by merge resolution;
        # --no-renames makes destinations ordinary additions (two fields).
        entries = git(
            "diff-tree", "--stdin", "-r", "-m", "-z", "--no-commit-id",
            "--no-renames", "--diff-filter=d", "--root", input=commits,
        ).split(b"\0")
        if entries.pop() != b"" or len(entries) % 2:
            raise RuntimeError("invalid git diff-tree output")
        seen: set[tuple[bytes, str]] = set()
        verdicts: dict[bytes, str | None] = {}
        with BlobReader() as blobs:
            for metadata, raw_path in zip(entries[::2], entries[1::2], strict=True):
                fields = metadata.split()
                if len(fields) != 5 or not fields[0].startswith(b":"):
                    raise RuntimeError("invalid git diff-tree entry")
                mode, oid = fields[1], fields[3]
                path = os.fsdecode(raw_path)
                key = oid, path
                if key in seen:
                    continue
                seen.add(key)
                reason = denied_name(path)
                # Gitlinks name commits in another repository, not blobs.
                # Their path is still subject to the name rules.
                if not reason and mode != b"160000":
                    if oid not in verdicts:
                        verdicts[oid] = denied_bytes(blobs.prefix(oid))
                    reason = verdicts[oid]
                report(path, reason)

    if reported:
        print(f"\ncheck-tracked-artifacts: refusing {len(reported)} file(s) above.", file=sys.stderr)
        print("Remove it from the commit (git rm --cached <path>) and add a matching", file=sys.stderr)
        print("pattern to .gitignore. If a file is legitimate, widen the rules in", file=sys.stderr)
        print("scripts/check_tracked_artifacts.py rather than skipping the check.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(scan(sys.argv[1:]))
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"check-tracked-artifacts: scan failed: {exc}", file=sys.stderr)
        sys.exit(2)
