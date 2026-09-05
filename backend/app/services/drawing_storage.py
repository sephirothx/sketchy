"""Operator check that every stored drawing is still readable.

A stored drawing is only as good as the decoder that can read it back, and
both of those - the checksum recorded beside the bytes, and the registry entry
naming the format - are silent until something asks. This walks the whole
store and asks.

It walks it, rather than looking at the first page: the earlier command
selected the oldest ``LIMIT batch_size`` rows and stopped, so repeated runs
verified the same prefix and reported "every drawing decoded" about rows it
had never visited (#610). The walk is a keyset over ``(created_at, turn_id)``
below a watermark taken when the run starts, so rows written during the scan
are out of scope rather than a moving target, and it can be resumed from the
cursor it prints. Payloads are fetched under a byte budget - metadata first,
then bytes in groups whose declared sizes fit - so the working set is bounded
by the budget rather than by ``batch_size`` times the 8 MiB row ceiling.

Each row is checked for what the metadata claims (declared size and format
against the bytes), what the digest says (checksum), whether this build can
read the format, and whether the decoded frame is structurally a canvas
history at all - the last of which normal reads skip, because a client
decodes the frame anyway and a scan is where a bad frame should be found.

It is also how a second stored format proves itself: after one is introduced,
a clean run is the evidence that every row written under either format still
decodes.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.canvas_history import decode_binary_canvas_history
from app.canvas_storage import (
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    stored_drawing_format,
    stored_drawing_wire_payload,
)
from app.db import init_db, maintenance_engine
from app.db.models import TurnDrawing
from app.domain_values import TurnDrawingStatus


DEFAULT_BATCH_SIZE = 500
DEFAULT_BYTE_BUDGET = 64 * 1024 * 1024
# How many failing rows a report names before it only counts them.
DEFAULT_REPORTED_ERRORS = 200


@dataclass(frozen=True)
class DrawingCursor:
    """Where a walk got to: the last row examined, in walk order."""

    created_at: datetime
    turn_id: UUID

    def __str__(self) -> str:
        return f"{self.created_at.isoformat()}/{self.turn_id}"

    @classmethod
    def parse(cls, value: str) -> DrawingCursor:
        created_at, _, turn_id = value.rpartition("/")
        return cls(datetime.fromisoformat(created_at), UUID(turn_id))


@dataclass
class DrawingVerification:
    checked: int = 0
    corrupt: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    #: Rows whose bytes live in an object store this build has no reader for,
    #: and rows erased between the metadata read and the payload read.
    skipped: int = 0
    #: Failures beyond the named ones, per kind, so a report stays bounded.
    unlisted: dict[str, int] = field(default_factory=dict)
    #: The walk covered every eligible row below the watermark.
    complete: bool = False
    cursor: DrawingCursor | None = None
    watermark: datetime | None = None

    @property
    def failed(self) -> int:
        return (
            len(self.corrupt)
            + len(self.unreadable)
            + len(self.malformed)
            + len(self.mismatched)
            + sum(self.unlisted.values())
        )

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def _note(self, kind: str, turn_id: UUID, limit: int) -> None:
        names: list[str] = getattr(self, kind)
        if len(names) < limit:
            names.append(str(turn_id))
        else:
            self.unlisted[kind] = self.unlisted.get(kind, 0) + 1


def _after(cursor: DrawingCursor | None):
    if cursor is None:
        return ()
    return (
        or_(
            TurnDrawing.created_at > cursor.created_at,
            and_(
                TurnDrawing.created_at == cursor.created_at,
                TurnDrawing.turn_id > cursor.turn_id,
            ),
        ),
    )


def _check(
    blob: bytes,
    *,
    byte_size: int | None,
    format_magic: str | None,
    format_version: int | None,
    checksum: str | None,
) -> str | None:
    """The kind of failure this row is, or None when it reads back whole."""
    if byte_size is not None and len(blob) != byte_size:
        return "mismatched"
    try:
        magic, version = stored_drawing_format(blob)
    except UnsupportedStoredDrawingError:
        return "unreadable"
    if (
        format_magic is not None and magic.decode("ascii", "replace") != format_magic
    ) or (format_version is not None and version != format_version):
        return "mismatched"
    try:
        wire = stored_drawing_wire_payload(blob, checksum=checksum or None)
    except CorruptStoredDrawingError:
        return "corrupt"
    except UnsupportedStoredDrawingError:
        return "unreadable"
    try:
        decode_binary_canvas_history(wire)
    except ValueError:
        return "malformed"
    return None


async def verify_stored_drawings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    byte_budget: int = DEFAULT_BYTE_BUDGET,
    cursor: DrawingCursor | None = None,
    watermark: datetime | None = None,
    max_rows: int | None = None,
    reported_errors: int = DEFAULT_REPORTED_ERRORS,
) -> DrawingVerification:
    """Walk every ready drawing below the watermark and report what failed.

    `batch_size` rows of metadata per query; payloads fetched in groups whose
    declared sizes sum to at most `byte_budget` (a row larger than the whole
    budget is fetched alone). `cursor` resumes a walk; `max_rows` stops one
    after that many rows, leaving `complete` False and `cursor` set.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if byte_budget < 1:
        raise ValueError("byte_budget must be at least 1")
    result = DrawingVerification(
        cursor=cursor, watermark=watermark or datetime.now(timezone.utc)
    )
    position = cursor
    async with session_factory() as session:
        while True:
            if max_rows is not None and result.checked + result.skipped >= max_rows:
                return result
            limit = batch_size
            if max_rows is not None:
                limit = min(limit, max_rows - result.checked - result.skipped)
            rows = (
                await session.execute(
                    select(
                        TurnDrawing.turn_id,
                        TurnDrawing.created_at,
                        TurnDrawing.byte_size,
                        TurnDrawing.format_magic,
                        TurnDrawing.format_version,
                        TurnDrawing.checksum_sha256,
                        TurnDrawing.object_key,
                        TurnDrawing.payload.is_not(None),
                    )
                    .where(
                        TurnDrawing.status == TurnDrawingStatus.READY.value,
                        TurnDrawing.created_at <= result.watermark,
                        *_after(position),
                    )
                    .order_by(TurnDrawing.created_at, TurnDrawing.turn_id)
                    .limit(limit)
                )
            ).all()
            if not rows:
                result.complete = True
                return result

            # Groups whose declared bytes fit the budget; an oversized row
            # travels alone. Declared, because the bytes are what we are
            # about to fetch; a row that lies about its size is caught below.
            group: list = []
            group_bytes = 0
            groups: list[list] = []
            for row in rows:
                declared = row.byte_size or 0
                if group and group_bytes + declared > byte_budget:
                    groups.append(group)
                    group, group_bytes = [], 0
                group.append(row)
                group_bytes += declared
            groups.append(group)

            for group in groups:
                inline = [row for row in group if row[7]]
                payloads: dict[UUID, bytes | None] = {}
                if inline:
                    payloads = dict(
                        (
                            await session.execute(
                                select(TurnDrawing.turn_id, TurnDrawing.payload).where(
                                    TurnDrawing.turn_id.in_([row.turn_id for row in inline])
                                )
                            )
                        ).all()
                    )
                for row in group:
                    blob = payloads.get(row.turn_id)
                    if blob is None:
                        # Object-backed (no reader yet, #471), or erased or
                        # otherwise gone since the metadata was read.
                        result.skipped += 1
                        continue
                    result.checked += 1
                    kind = _check(
                        bytes(blob),
                        byte_size=row.byte_size,
                        format_magic=row.format_magic,
                        format_version=row.format_version,
                        checksum=row.checksum_sha256,
                    )
                    if kind is not None:
                        result._note(kind, row.turn_id, reported_errors)
                del payloads
            last = rows[-1]
            position = DrawingCursor(created_at=last.created_at, turn_id=last.turn_id)
            result.cursor = position
            if len(rows) < limit:
                result.complete = True
                return result


async def _run(args) -> DrawingVerification:
    engine, factory = maintenance_engine()
    try:
        await init_db(engine)
        return await verify_stored_drawings(
            factory,
            batch_size=args.batch_size,
            byte_budget=args.byte_budget_mib * 1024 * 1024,
            cursor=DrawingCursor.parse(args.resume_from) if args.resume_from else None,
            max_rows=args.max_rows,
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk every stored drawing, decode it, and report what failed."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--byte-budget-mib",
        type=int,
        default=DEFAULT_BYTE_BUDGET // (1024 * 1024),
        help="Declared payload bytes fetched at once, in MiB.",
    )
    parser.add_argument(
        "--resume-from",
        help="A cursor printed by a previous partial run (created_at/turn_id).",
    )
    parser.add_argument(
        "--max-rows", type=int, help="Stop after this many rows and print the cursor."
    )
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(f"Checked {result.checked} stored drawings, skipped {result.skipped}.")
    for kind, label in (
        ("corrupt", "Failed checksum"),
        ("unreadable", "No decoder"),
        ("malformed", "Decoded to no valid canvas history"),
        ("mismatched", "Bytes disagree with their metadata"),
    ):
        names = getattr(result, kind)
        if names:
            more = result.unlisted.get(kind, 0)
            suffix = f" and {more} more" if more else ""
            print(f"{label} ({len(names)}{suffix}): {', '.join(names)}")
    if not result.complete:
        print(f"Partial: stopped at cursor {result.cursor}; resume with --resume-from.")
        raise SystemExit(2 if result.ok else 1)
    if result.unreadable:
        print("Unsupported: some rows name a format this build cannot read.")
        raise SystemExit(3 if not (result.corrupt or result.malformed or result.mismatched) else 1)
    if result.ok:
        print(f"Complete: every drawing below {result.watermark.isoformat()} decoded.")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
