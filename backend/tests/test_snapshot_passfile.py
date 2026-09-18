"""The snapshot script's passfile is one libpq will match (#893).

`ops/postgres/migrate-with-snapshot.sh` hands the owner's password to `psql`
and `pg_dump` through a passfile rather than argv. libpq reads each line as
`hostname:port:database:username:password`, with `:` and `\\` escaped; a line
in any other order simply never matches, and the dump then fails for want of
a password. So the script's own Python is run here on a URL whose database
and user differ, as they do in every deployment.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "postgres" / "migrate-with-snapshot.sh"


def _passfile_program() -> str:
    found = re.search(r"<<'PY'\n(.*?)\nPY\n", SCRIPT.read_text(encoding="utf-8"), re.DOTALL)
    assert found, "the script no longer writes its passfile with an embedded program"
    return found.group(1)


def test_the_passfile_line_is_host_port_database_user_password(tmp_path):
    passfile = tmp_path / "passfile"
    completed = subprocess.run(
        [sys.executable, "-c", _passfile_program()],
        env={
            "MIGRATION_DATABASE_URL": "postgresql+asyncpg://sketchy_owner:a%3Ab%5Cc%40d@db:6543/sketchy?sslmode=require",
            "PASSFILE": str(passfile),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert passfile.read_text(encoding="utf-8") == "db:6543:sketchy:sketchy_owner:a\\:b\\\\c@d\n"
    assert completed.stdout.rstrip("\n").split("\t") == ["db", "6543", "sketchy_owner", "sketchy", "require"]
