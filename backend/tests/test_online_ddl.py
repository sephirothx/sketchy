"""A revision written after the launch baseline must be safe to run over live rows (#893).

The migration role's five-second `lock_timeout` makes an unsafe revision fail
rather than stall play - but it fails at deploy time, halfway, on the largest
tables. A plain `CREATE INDEX` on `room_messages` holds a lock that blocks every
writer for as long as the build takes; a constraint added in one step scans the
whole table under that lock; a column rewrite does both. So this reads every
revision newer than `LINT_FROM` and refuses, on the tables in `LARGE_TABLES`:

- `create_index` without `postgresql_concurrently=True` (which also needs the
  operation inside `op.get_context().autocommit_block()`, since `CONCURRENTLY`
  cannot run in a transaction);
- `create_check_constraint` / `create_foreign_key` without
  `postgresql_not_valid=True`, followed by a separate
  `ALTER TABLE ... VALIDATE CONSTRAINT`, which takes a lock that lets writes
  through;
- `alter_column` changing a type or setting `nullable=False` - a rewrite, or a
  scan under an exclusive lock - where a validated `CHECK (col IS NOT NULL)`
  first lets PostgreSQL skip the scan;
- `add_column` with `nullable=False` and no `server_default`, which fails
  outright on a table with rows;
- `op.execute` of an `UPDATE` or `DELETE` on one of them, which must be batched.

A call that is safe for a reason this cannot see says so on its line, or the
line above: `# online-ddl: <why>`. `docs/database.md` *Adding a table or
column* carries the same rules with their reasons.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

# Every revision up to and including this one ran before the rules existed and
# before any deployment held rows; the lint starts after it.
LINT_FROM = "c3e4f5a6b7d8"

# The tables that grow with play and traffic, where a lock held for a scan is
# felt by players. A small table - a configuration row, a reservation, a
# moderator's queue - is left out on purpose: its lock is milliseconds.
LARGE_TABLES = frozenset(
    {
        "audit_events",
        "auth_sessions",
        "finished_game_envelopes",
        "friendships",
        "game_participants",
        "game_records",
        "prompt_list_stars",
        "prompt_usage_facts",
        "room_messages",
        "runtime_events",
        "score_events",
        "turn_drawing_reactions",
        "turn_drawings",
        "turn_participant_outcomes",
        "turn_prompt_offer_sources",
        "turn_prompt_offers",
        "turn_records",
        "user_stats_daily",
        "users",
    }
)

ESCAPE = re.compile(r"#\s*online-ddl:\s*\S")
WRITE = re.compile(r"\b(UPDATE|DELETE\s+FROM)\s+\"?([a-z_]+)", re.IGNORECASE)


def _keyword(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _string(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _table(call: ast.Call, position: int, keyword: str, batch_table: str | None) -> str | None:
    if batch_table is not None:
        return batch_table
    node = _keyword(call, keyword)
    if node is None and len(call.args) > position:
        node = call.args[position]
    return _string(node)


def lint_revision(source: str, name: str = "<revision>") -> list[str]:
    """Every unsafe operation in one revision's `upgrade()`, as messages."""
    tree = ast.parse(source)
    lines = source.splitlines()
    upgrade = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"),
        None,
    )
    if upgrade is None:
        return []

    def escaped(node: ast.AST) -> bool:
        for number in (node.lineno, node.lineno - 1):
            if 1 <= number <= len(lines) and ESCAPE.search(lines[number - 1]):
                return True
        return False

    problems: list[str] = []
    # A table this revision creates is empty while it runs: nothing to lock out.
    created = {
        _string(node.args[0])
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_table"
        and node.args
    }
    large = LARGE_TABLES - created

    def visit(node: ast.AST, batch_table: str | None) -> None:
        if isinstance(node, ast.With):
            table = batch_table
            for item in node.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "batch_alter_table"
                ):
                    table = _string(call.args[0]) if call.args else _string(_keyword(call, "table_name"))
            for child in node.body:
                visit(child, table)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not escaped(node):
            check(node, node.func.attr, batch_table)
        for child in ast.iter_child_nodes(node):
            visit(child, batch_table)

    def check(call: ast.Call, operation: str, batch_table: str | None) -> None:
        where = f"{name}:{call.lineno}"
        if operation == "create_index":
            table = _table(call, 1, "table_name", batch_table)
            if table in large and not _is_true(_keyword(call, "postgresql_concurrently")):
                problems.append(f"{where}: create_index on {table} without postgresql_concurrently")
        elif operation in ("create_check_constraint", "create_foreign_key"):
            table = _table(call, 1, "table_name" if operation == "create_check_constraint" else "source_table", batch_table)
            if table in large and not _is_true(_keyword(call, "postgresql_not_valid")):
                problems.append(f"{where}: {operation} on {table} without postgresql_not_valid")
        elif operation == "alter_column":
            table = _table(call, 0, "table_name", batch_table)
            if table in large:
                if _keyword(call, "type_") is not None:
                    problems.append(f"{where}: alter_column changes a type on {table}")
                nullable = _keyword(call, "nullable")
                if isinstance(nullable, ast.Constant) and nullable.value is False:
                    problems.append(f"{where}: alter_column sets NOT NULL on {table}")
        elif operation == "add_column":
            table = _table(call, 0, "table_name", batch_table)
            column = call.args[-1] if call.args else _keyword(call, "column")
            if table in large and isinstance(column, ast.Call):
                nullable = _keyword(column, "nullable")
                if (
                    isinstance(nullable, ast.Constant)
                    and nullable.value is False
                    and _keyword(column, "server_default") is None
                ):
                    problems.append(f"{where}: add_column NOT NULL without server_default on {table}")
        elif operation == "execute":
            statement = _string(call.args[0]) if call.args else None
            for _verb, table in WRITE.findall(statement or ""):
                if table in large:
                    problems.append(f"{where}: unbatched write to {table} in op.execute")

    for statement in upgrade.body:
        visit(statement, None)
    return problems


def _revisions_after(revision: str) -> list[Path]:
    """The revision files newer than `revision`, found by their down_revision links."""
    down_of: dict[str, tuple[str, Path]] = {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = re.search(r'^revision(?:\s*:[^=]+)?\s*=\s*["\']([0-9a-f]+)', text, re.MULTILINE)
        parent = re.search(r'^down_revision(?:\s*:[^=]+)?\s*=\s*["\']([0-9a-f]+)', text, re.MULTILINE)
        if found and parent:
            down_of[found.group(1)] = (parent.group(1), path)
    newer: list[Path] = []
    frontier = {revision}
    while True:
        children = [(rev, path) for rev, (parent, path) in down_of.items() if parent in frontier]
        if not children:
            return newer
        newer.extend(path for _, path in children)
        frontier = {rev for rev, _ in children}


def test_every_revision_after_the_baseline_is_safe_over_live_rows():
    problems = [
        problem
        for path in _revisions_after(LINT_FROM)
        for problem in lint_revision(path.read_text(encoding="utf-8"), path.name)
    ]
    assert problems == [], "\n".join(problems)


def test_the_lint_starts_from_a_revision_that_exists():
    assert any(path.name.startswith(LINT_FROM) for path in VERSIONS.glob("*.py"))


# --- the rules, each proven on an unsafe revision -----------------------------

UNSAFE = '''
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_index("ix_room_messages_x", "room_messages", ["x"])
    op.create_check_constraint("ck_users_x", "users", "x > 0")
    op.create_foreign_key("fk_x", "turn_records", "users", ["x"], ["id"])
    op.alter_column("turn_drawings", "x", type_=sa.BigInteger())
    op.alter_column("game_records", "x", nullable=False)
    op.add_column("score_events", sa.Column("x", sa.Integer(), nullable=False))
    op.execute("UPDATE runtime_events SET value = 0")
    with op.batch_alter_table("audit_events") as batch:
        batch.create_index("ix_audit_x", ["x"])

def downgrade():
    op.drop_index("ix_room_messages_x", table_name="room_messages")
'''

SAFE = '''
from alembic import op
import sqlalchemy as sa

def upgrade():
    with op.get_context().autocommit_block():
        op.create_index("ix_room_messages_x", "room_messages", ["x"], postgresql_concurrently=True)
    op.create_check_constraint("ck_users_x", "users", "x > 0", postgresql_not_valid=True)
    op.execute("ALTER TABLE users VALIDATE CONSTRAINT ck_users_x")
    op.add_column("score_events", sa.Column("x", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_app_config_x", "app_config", ["x"])
    op.create_table("turn_novelties", sa.Column("id", sa.Integer(), primary_key=True))
    op.create_index("ix_turn_novelties_id", "turn_novelties", ["id"])
    # online-ddl: the column was added empty in the previous revision
    op.alter_column("game_records", "x", nullable=False)
'''


def test_each_rule_refuses_its_unsafe_operation():
    problems = lint_revision(UNSAFE, "unsafe.py")
    expected = [
        "create_index on room_messages",
        "create_check_constraint on users",
        "create_foreign_key on turn_records",
        "alter_column changes a type on turn_drawings",
        "alter_column sets NOT NULL on game_records",
        "add_column NOT NULL without server_default on score_events",
        "unbatched write to runtime_events",
        "create_index on audit_events",
    ]
    assert len(problems) == len(expected), problems
    for fragment in expected:
        assert any(fragment in problem for problem in problems), fragment


def test_the_safe_forms_and_a_stated_reason_pass():
    assert lint_revision(SAFE, "safe.py") == []
