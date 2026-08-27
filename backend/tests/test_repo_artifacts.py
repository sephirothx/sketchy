"""The repository must not carry databases, env files, or private keys.

It has twice: a SQLite write-ahead log, then a whole 344KB database pushed to a
public remote. `scripts/check-tracked-artifacts.sh` is what refuses the third
time, in CI and in an opt-in pre-push hook. These tests keep it honest, because a
guard that silently stops matching is worse than no guard - it makes the checkbox
look ticked.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check-tracked-artifacts.sh"

# "SQLite format 3\0" - the header the checker sniffs for.
SQLITE_MAGIC = b"SQLite format 3\x00"


def run_checker(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(CHECKER), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


requires_git = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
    reason="needs a git work tree",
)


@requires_git
def test_this_repository_is_clean():
    result = run_checker(REPO_ROOT)
    assert result.returncode == 0, result.stderr


@requires_git
def test_a_database_is_refused_under_an_innocuous_name(tmp_path):
    """The name rules only match shapes someone already thought of. Both real
    incidents were named something .gitignore did not expect, so the byte sniff
    is the rule that has to hold."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "notes.txt").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "looks like notes")

    result = run_checker(repo)

    assert result.returncode == 1
    assert "notes.txt" in result.stderr
    assert "SQLite database" in result.stderr


@requires_git
def test_a_backup_suffixed_database_is_refused_by_name(tmp_path):
    """`*.db` does not match `sketchy.db.broken-20260827-033005`. That is exactly
    how the second incident got past .gitignore."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "sketchy.db.broken-20260827-033005").write_text("not even a real database")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "backup copy")

    result = run_checker(repo)

    assert result.returncode == 1
    assert "sketchy.db.broken-20260827-033005" in result.stderr


@requires_git
def test_a_file_added_and_deleted_in_one_push_still_fails(tmp_path):
    """Deleting the file in a later commit cleans the tree and leaves the blob in
    history forever, which is the state this repository is now in. The pre-push
    hook scans the range, not just the tip."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "keep.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repo / "oops.txt").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add it")
    git(repo, "rm", "-q", "oops.txt")
    git(repo, "commit", "-qm", "remove it again")

    assert run_checker(repo).returncode == 0

    ranged = run_checker(repo, "--range", f"{base}..HEAD")

    assert ranged.returncode == 1
    assert "oops.txt" in ranged.stderr


@requires_git
def test_an_example_env_file_is_allowed(tmp_path):
    """.gitignore deliberately un-ignores `.env.example`, so the checker must not
    contradict it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / ".env.example").write_text("DATABASE_URL=\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "example env")

    assert run_checker(repo).returncode == 0
