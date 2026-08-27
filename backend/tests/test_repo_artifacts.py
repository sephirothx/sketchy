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

PEM_ARMOUR = (
    "PRIVATE KEY",
    "RSA PRIVATE KEY",
    "EC PRIVATE KEY",
    "OPENSSH PRIVATE KEY",
    "ENCRYPTED PRIVATE KEY",
    "PGP PRIVATE KEY BLOCK",
)


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
def test_a_tracked_file_overwritten_with_a_database_is_refused(tmp_path):
    """Not every artifact arrives as a new file. A placeholder that gets replaced
    with the real database is a modification, and its blob reaches history just
    the same - so the range scan cannot look only at additions."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "config.json").write_text('{"placeholder": true}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "placeholder")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repo / "config.json").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "swap in the real thing")
    git(repo, "rm", "-q", "config.json")
    git(repo, "commit", "-qm", "tidy up")

    ranged = run_checker(repo, "--range", f"{base}..HEAD")

    assert ranged.returncode == 1
    assert "config.json" in ranged.stderr


@requires_git
def test_a_renamed_database_is_refused_with_rename_detection_on(tmp_path):
    """`diff.renames` turns the add half of a rename into an R, which a filter
    looking for additions would skip - and makes git emit a third path field that
    would desynchronise the parser."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "diff.renames", "true")

    (repo / "staged.bin").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add under one name")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    git(repo, "mv", "staged.bin", "harmless.txt")
    git(repo, "commit", "-qm", "rename it")
    git(repo, "rm", "-q", "harmless.txt")
    git(repo, "commit", "-qm", "and delete it")

    ranged = run_checker(repo, "--range", f"{base}..HEAD")

    assert ranged.returncode == 1
    assert "harmless.txt" in ranged.stderr


@requires_git
def test_a_benign_overwrite_does_not_hide_the_blob_beneath_it(tmp_path):
    """`git rev-list` walks newest first, and the tracked-tree scan runs before
    the range scan. Dedupe on the path alone lets the harmless version of a file
    be seen first and mark the path done, hiding the database that sat at the
    same path earlier in the very same push. The identity that matters is the
    content, not the name."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "seed.txt").write_text("seed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    (repo / "notes.txt").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "database under an innocuous name")

    # Survives to the tip, so the tracked-tree scan reaches this path first.
    (repo / "notes.txt").write_text("genuinely notes now\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "overwrite")

    ranged = run_checker(repo, "--range", f"{base}..HEAD")

    assert ranged.returncode == 1
    assert "notes.txt" in ranged.stderr


@requires_git
@pytest.mark.parametrize("armour", PEM_ARMOUR)
def test_a_private_key_is_refused_under_an_innocuous_name(armour, tmp_path):
    """A database gets caught by its bytes; a key used to be caught only by its
    extension, so `id_ed25519` renamed to `deploy-notes.txt` walked through. The
    same backstop applies to PEM armour."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "deploy-notes.txt").write_text(
        f"-----BEGIN {armour}-----\nZm9vYmFy\n-----END {armour}-----\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a key by another name")

    result = run_checker(repo)

    assert result.returncode == 1
    assert "deploy-notes.txt" in result.stderr
    assert "PEM private key" in result.stderr


@requires_git
@pytest.mark.parametrize("armour", ["PUBLIC KEY", "CERTIFICATE"])
def test_public_pem_material_is_not_refused(armour, tmp_path):
    """The sniff has to be narrow enough to leave a certificate alone, or nobody
    can commit a trust store."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "trust.dat").write_text(
        f"-----BEGIN {armour}-----\nZm9vYmFy\n-----END {armour}-----\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "public material")

    assert run_checker(repo).returncode == 0


@requires_git
def test_a_secret_introduced_only_by_a_merge_is_refused(tmp_path):
    """`git diff-tree` prints nothing at all for a merge commit unless asked for
    a per-parent diff, so a conflict resolved by pasting in the wrong file left
    no trace in the range scan."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", ".")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")

    (repo / "f.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    git(repo, "checkout", "-qb", "side")
    (repo / "f.txt").write_text("side\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "side")

    git(repo, "checkout", "-q", base, "-B", "trunk")
    (repo / "f.txt").write_text("trunk\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "trunk")

    # Conflicts, which is the point: the resolution is where the secret enters,
    # and it exists in neither parent.
    subprocess.run(["git", "merge", "side"], cwd=repo, capture_output=True)
    (repo / "f.txt").write_text("resolved\n")
    (repo / "notes.txt").write_bytes(SQLITE_MAGIC + b"\x00" * 512)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "resolve the conflict")

    # Gone by the tip, so only the merge commit carries it.
    git(repo, "rm", "-q", "notes.txt")
    git(repo, "commit", "-qm", "tidy up")

    ranged = run_checker(repo, "--range", f"{base}..HEAD")

    assert ranged.returncode == 1
    assert "notes.txt" in ranged.stderr


def is_shallow() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


@requires_git
@pytest.mark.skipif(
    is_shallow(),
    reason="a shallow checkout has no history to resolve the baseline against",
)
def test_the_baseline_is_a_commit_in_this_history():
    """The hook and CI both take their floor from `--baseline`. A sha that does
    not resolve would send both of them to their weakest fallback without
    saying so.

    Only answerable where the history is actually present. The backend CI job
    clones one commit deep, so this cannot run there - `.github/workflows/ci.yml`
    makes the artifact-scan job, which clones in full, fail on a baseline that
    stops resolving.
    """
    baseline = subprocess.run(
        ["bash", str(CHECKER), "--baseline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    resolved = subprocess.run(
        ["git", "cat-file", "-e", f"{baseline}^{{commit}}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )

    assert resolved.returncode == 0, f"baseline {baseline!r} is not a commit here"

    # And the floor has to be usable: scanning from it must not trip over the
    # artifact whose presence in history is the reason it exists.
    assert run_checker(REPO_ROOT, "--range", f"{baseline}..HEAD").returncode == 0


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
