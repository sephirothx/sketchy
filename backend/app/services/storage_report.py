"""What each table occupies in the live database, safe to paste into an issue (#895).

Every storage decision so far rested on synthetic shapes: a seeded population,
a drawing built from modular arithmetic, 8 seats by 24 turns. The benchmarks
print the numbers those decisions needed - heap, TOAST and index bytes, rows,
bytes per row and per finished game - but from a seed. This prints the same
numbers from the database the service is actually running on, so the next
review closes on evidence.

Read-only and PostgreSQL-only: sizes come from the catalogue
(`pg_table_size`, `pg_indexes_size`, the TOAST relation) and rows from the
planner's estimate (`pg_class.reltuples`), so it scans no table and holds no
lock anybody waits for. It prints no personal content: table and index names,
byte counts and row estimates only.

    python -m app.services.storage_report            # text
    python -m app.services.storage_report --json     # for a script
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import GameRecord

LARGEST_INDEXES = 10


@dataclass(frozen=True)
class TableFootprint:
    table: str
    rows: int
    heap_bytes: int
    toast_bytes: int
    index_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.heap_bytes + self.toast_bytes + self.index_bytes

    @property
    def bytes_per_row(self) -> float | None:
        return round(self.total_bytes / self.rows, 1) if self.rows else None


@dataclass(frozen=True)
class IndexFootprint:
    index: str
    table: str
    bytes: int


@dataclass(frozen=True)
class StorageReport:
    database_bytes: int
    finished_games: int
    tables: tuple[TableFootprint, ...]
    largest_indexes: tuple[IndexFootprint, ...]

    @property
    def bytes_per_finished_game(self) -> float | None:
        if not self.finished_games:
            return None
        return round(sum(table.total_bytes for table in self.tables) / self.finished_games, 1)

    def as_json(self) -> dict[str, object]:
        # snake_case: this is an operator command's output, not a wire payload.
        return {
            "database_bytes": self.database_bytes,
            "finished_games": self.finished_games,
            "bytes_per_finished_game": self.bytes_per_finished_game,
            "tables": [
                {**asdict(table), "total_bytes": table.total_bytes, "bytes_per_row": table.bytes_per_row}
                for table in self.tables
            ],
            "largest_indexes": [asdict(index) for index in self.largest_indexes],
        }


class StorageReportUnavailable(RuntimeError):
    """The database has no size catalogue to read (SQLite)."""


async def read_storage_report(session: AsyncSession) -> StorageReport:
    if session.get_bind().dialect.name != "postgresql":
        raise StorageReportUnavailable("the storage report reads PostgreSQL's catalogue")
    tables = tuple(
        TableFootprint(
            table=name,
            rows=max(int(rows), 0),
            heap_bytes=int(heap),
            toast_bytes=int(toast),
            index_bytes=int(indexes),
        )
        for name, rows, heap, toast, indexes in (
            await session.execute(
                text(
                    # Heap with its free-space and visibility maps, TOAST
                    # with its own index, then the table's indexes: the three
                    # add up to pg_total_relation_size, which orders them.
                    "SELECT c.relname, c.reltuples::bigint, "
                    "pg_table_size(c.oid) - COALESCE(pg_total_relation_size(NULLIF(c.reltoastrelid, 0)), 0), "
                    "COALESCE(pg_total_relation_size(NULLIF(c.reltoastrelid, 0)), 0), "
                    "pg_indexes_size(c.oid) "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relkind = 'r' "
                    "ORDER BY pg_total_relation_size(c.oid) DESC, c.relname"
                )
            )
        ).all()
    )
    indexes = tuple(
        IndexFootprint(index=name, table=table, bytes=int(size))
        for name, table, size in (
            await session.execute(
                text(
                    "SELECT i.relname, t.relname, pg_relation_size(i.oid) "
                    "FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
                    "JOIN pg_class t ON t.oid = x.indrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = current_schema() "
                    "ORDER BY pg_relation_size(i.oid) DESC, i.relname LIMIT :limit"
                ),
                {"limit": LARGEST_INDEXES},
            )
        ).all()
    )
    database_bytes = int(await session.scalar(text("SELECT pg_database_size(current_database())")))
    # Exact, but over the one table whose rows are games: small next to the
    # tables it is divided into.
    finished_games = int(await session.scalar(select(func.count()).select_from(GameRecord)) or 0)
    return StorageReport(
        database_bytes=database_bytes,
        finished_games=finished_games,
        tables=tables,
        largest_indexes=indexes,
    )


def _size(value: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} GB"


def format_report(report: StorageReport) -> str:
    lines = [
        f"Database {_size(report.database_bytes)}; {report.finished_games:,} finished games"
        + (
            f"; {_size(report.bytes_per_finished_game)} per finished game, every table included"
            if report.bytes_per_finished_game is not None
            else ""
        ),
        "",
        f"{'table':<36} {'rows':>12} {'heap':>11} {'toast':>11} {'indexes':>11} {'total':>11} {'B/row':>9}",
    ]
    for table in report.tables:
        per_row = "" if table.bytes_per_row is None else f"{table.bytes_per_row:,.0f}"
        lines.append(
            f"{table.table:<36} {table.rows:>12,} {_size(table.heap_bytes):>11} "
            f"{_size(table.toast_bytes):>11} {_size(table.index_bytes):>11} "
            f"{_size(table.total_bytes):>11} {per_row:>9}"
        )
    lines += ["", f"{LARGEST_INDEXES} largest indexes:"]
    lines += [f"  {index.index:<52} {index.table:<30} {_size(index.bytes):>11}" for index in report.largest_indexes]
    lines += ["", "Rows are the planner's estimate (pg_class.reltuples), as of the last analyze."]
    return "\n".join(lines)


async def run_report(session_factory: async_sessionmaker[AsyncSession]) -> StorageReport:
    async with session_factory() as session:
        return await read_storage_report(session)


async def _run_cli(as_json: bool) -> int:
    from app.db import maintenance_engine

    engine, factory = maintenance_engine()
    try:
        try:
            report = await run_report(factory)
        except StorageReportUnavailable as error:
            print(f"storage_report: {error}")
            return 2
        print(json.dumps(report.as_json(), indent=2) if as_json else format_report(report))
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print what each table occupies in the live PostgreSQL database."
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_cli(args.json)))


if __name__ == "__main__":
    main()
