"""The stored-drawing verifier walks the whole store, bounded, and can resume (#610)."""
from __future__ import annotations

import hashlib
import tracemalloc
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import event, select, update

from app.db.models import TurnDrawing, generate_uuid
from app.services.drawing_storage import DrawingCursor, verify_stored_drawings

from tests.dbfixtures import create_test_db
from tests.test_repositories import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    TurnDrawingInput,
    _save_game_with_drawings,
    _skch_bytes,
)


async def _store(factory, count: int, *, spacing_seconds: float = 1.0) -> list[UUID]:
    """`count` ready drawings with ascending, distinct creation times."""
    user_repo = SqlAlchemyUserRepository(factory)
    history_repo = SqlAlchemyGameHistoryRepository(factory)
    base = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    turn_ids: list[UUID] = []
    for index in range(count):
        _, turn_id, _, _ = await _save_game_with_drawings(
            history_repo,
            user_repo,
            lambda tid: [TurnDrawingInput(turn_id=tid, payload=_skch_bytes())],
        )
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(TurnDrawing)
                    .where(TurnDrawing.turn_id == UUID(turn_id))
                    .values(created_at=base + timedelta(seconds=index * spacing_seconds))
                )
        turn_ids.append(UUID(turn_id))
    return turn_ids


async def _damage(factory, turn_id: UUID, *, rehash: bool = False) -> None:
    async with factory() as session:
        async with session.begin():
            row = await session.get(TurnDrawing, turn_id)
            damaged = bytearray(row.payload)
            damaged[-1] ^= 0x01
            row.payload = bytes(damaged)
            if rehash:
                row.checksum_sha256 = hashlib.sha256(bytes(damaged)).hexdigest()


async def test_a_corrupt_row_on_the_second_page_is_found():
    """The reproduction: two rows, the second corrupt, batch size one. The
    old command reported "every drawing decoded" twice."""
    factory, engine = await create_test_db()
    try:
        first, second = await _store(factory, 2)
        await _damage(factory, second)

        result = await verify_stored_drawings(factory, batch_size=1)

        assert result.complete and result.checked == 2
        assert result.corrupt == [str(second)] and not result.ok
    finally:
        await engine.dispose()


async def test_equal_timestamps_are_walked_deterministically_and_exactly_once():
    factory, engine = await create_test_db()
    try:
        turn_ids = await _store(factory, 5, spacing_seconds=0)
        seen: list[UUID] = []
        cursor = None
        while True:
            page = await verify_stored_drawings(factory, batch_size=2, cursor=cursor, max_rows=2)
            seen.extend([])  # rows are counted, not listed; the cursor is the proof
            if page.complete:
                break
            cursor = page.cursor
        assert cursor is not None and page.cursor is not None
        # Three pages of two, two, one: the last cursor is the largest turn id
        # among the equal timestamps, which is the walk's tie-break.
        assert page.cursor.turn_id == max(turn_ids)
        assert page.checked == 1
    finally:
        await engine.dispose()


async def test_a_walk_resumes_from_its_cursor_without_repeating_or_skipping():
    factory, engine = await create_test_db()
    try:
        turn_ids = await _store(factory, 7)
        await _damage(factory, turn_ids[5])

        first = await verify_stored_drawings(factory, batch_size=3, max_rows=3)
        assert not first.complete and first.checked == 3 and first.ok
        assert first.cursor == DrawingCursor(
            created_at=(await _created_at(factory, turn_ids[2])), turn_id=turn_ids[2]
        )

        rest = await verify_stored_drawings(
            factory, batch_size=3, cursor=DrawingCursor.parse(str(first.cursor))
        )
        assert rest.complete and rest.checked == 4
        assert rest.corrupt == [str(turn_ids[5])]
    finally:
        await engine.dispose()


async def _created_at(factory, turn_id: UUID) -> datetime:
    async with factory() as session:
        value = await session.scalar(
            select(TurnDrawing.created_at).where(TurnDrawing.turn_id == turn_id)
        )
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def test_rows_written_after_the_watermark_and_rows_erased_during_the_walk():
    factory, engine = await create_test_db()
    try:
        turn_ids = await _store(factory, 4)
        watermark = await _created_at(factory, turn_ids[2])
        # Erased between the metadata read and the payload read: the walk
        # reads metadata a page at a time, so erase before the page that
        # would hold it is fetched by giving the erasure the first page.
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(TurnDrawing)
                    .where(TurnDrawing.turn_id == turn_ids[1])
                    .values(payload=None, status="deleted", checksum_sha256=None,
                            byte_size=None, format_magic=None, format_version=None,
                            deleted_at=datetime.now(timezone.utc))
                )

        result = await verify_stored_drawings(factory, batch_size=10, watermark=watermark)

        assert result.complete
        assert result.checked == 2, "rows 0 and 2; row 1 erased, row 3 after the watermark"
        assert result.skipped == 0 and result.ok
    finally:
        await engine.dispose()


def _big_frame(paths: int = 1_200) -> bytes:
    """A valid SKCH frame of a few hundred kilobytes, built the way a game does."""
    from app.canvas_history import PackedCanvasHistory

    history = PackedCanvasHistory()
    for index in range(paths):
        history.append_path(
            [((index + point) % 800 / 800, (index * 3 + point) % 600 / 600) for point in range(20)],
            color=(index * 977) & 0xFFFFFF,
            width=index % 12 + 1,
        )
    return history.binary_payload()


async def test_payloads_are_fetched_within_the_byte_budget():
    factory, engine = await create_test_db()
    try:
        frame = _big_frame()
        size = len(frame)
        assert size > 100_000, "the budget only means something against real sizes"
        turn_ids = await _store(factory, 12)
        async with factory() as session:
            async with session.begin():
                for turn_id in turn_ids:
                    row = await session.get(TurnDrawing, turn_id)
                    row.payload = frame
                    row.byte_size = size
                    row.checksum_sha256 = hashlib.sha256(frame).hexdigest()
        statements: list[str] = []

        def before(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)

        tracemalloc.start()
        result = await verify_stored_drawings(factory, batch_size=12, byte_budget=size * 2)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert result.complete and result.checked == 12 and result.ok
        payload_fetches = [
            s for s in statements
            if s.lstrip().startswith("SELECT") and "turn_drawings.payload" in s
            and "IS NOT NULL" not in s
        ]
        assert len(payload_fetches) == 6, "twelve rows, two per budget-sized group"
        # Two payloads in flight, their decoded frames and the driver's own
        # buffers: less than the twelve payloads the old page fetch held at
        # once, and independent of how many rows the batch names.
        assert peak < size * 12, f"peak {peak} bytes for twelve {size}-byte payloads"
        assert len(turn_ids) == 12
    finally:
        await engine.dispose()


async def test_metadata_that_disagrees_with_the_bytes_and_a_frame_that_is_no_history():
    factory, engine = await create_test_db()
    try:
        lying, hollow, fine = await _store(factory, 3)
        async with factory() as session:
            async with session.begin():
                # The declared size is held to the bytes by the database now
                # (#553); the format metadata is the disagreement left to find.
                await session.execute(
                    update(TurnDrawing).where(TurnDrawing.turn_id == lying).values(format_version=9)
                )
                row = await session.get(TurnDrawing, hollow)
                # A well-formed header over garbage, checksum recomputed: the
                # digest is right, the format is known, the frame is nonsense.
                body = bytearray(row.payload)
                for index in range(12, len(body)):
                    body[index] = 0xFF
                row.payload = bytes(body)
                row.checksum_sha256 = hashlib.sha256(bytes(body)).hexdigest()

        result = await verify_stored_drawings(factory)

        assert result.complete and result.checked == 3
        assert result.mismatched == [str(lying)]
        assert result.malformed == [str(hollow)]
        assert not result.corrupt and not result.unreadable
        assert fine not in {UUID(x) for x in result.mismatched + result.malformed}
    finally:
        await engine.dispose()


async def test_the_report_names_only_so_many_failures_and_counts_the_rest():
    factory, engine = await create_test_db()
    try:
        turn_ids = await _store(factory, 4)
        for turn_id in turn_ids:
            await _damage(factory, turn_id)
        result = await verify_stored_drawings(factory, reported_errors=2)
        assert len(result.corrupt) == 2 and result.unlisted == {"corrupt": 2}
        assert result.failed == 4
    finally:
        await engine.dispose()


def test_a_cursor_round_trips_through_its_printed_form():
    cursor = DrawingCursor(
        created_at=datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc),
        turn_id=generate_uuid(),
    )
    assert DrawingCursor.parse(str(cursor)) == cursor


async def test_a_store_holding_both_formats_verifies_each_with_its_own_decoder():
    """SKCH v1 rows predate #547 and stay; SKCD v1 is what is written now. A
    walk over both checks each against its own decoder, and a compressed row
    whose metadata claims the old format is a mismatch, not a decode."""
    from app.canvas_storage import (
        STORED_DELTA_MAGIC,
        prepare_stored_drawing,
        stored_drawing_checksum,
    )
    from tests.test_canvas_storage import _stroke_history

    factory, engine = await create_test_db()
    try:
        old_format, compressed, mislabelled = await _store(factory, 3)
        stroke_frame = _stroke_history(11).binary_payload()
        async with factory() as session:
            async with session.begin():
                # The writer stores a frame this small as it travels (SKCH).
                row = await session.get(TurnDrawing, old_format)
                assert row.format_magic == "SKCH"
                for turn_id in (compressed, mislabelled):
                    row = await session.get(TurnDrawing, turn_id)
                    blob, magic, version, checksum = prepare_stored_drawing(stroke_frame)
                    assert magic == STORED_DELTA_MAGIC
                    row.payload, row.byte_size, row.checksum_sha256 = blob, len(blob), checksum
                    row.format_magic, row.format_version = magic.decode(), version
                row = await session.get(TurnDrawing, mislabelled)
                row.format_magic = "SKCH"
                assert stored_drawing_checksum(row.payload) == row.checksum_sha256

        result = await verify_stored_drawings(factory)

        assert result.complete and result.checked == 3
        assert result.mismatched == [str(mislabelled)]
        assert not result.corrupt and not result.malformed and not result.unreadable
    finally:
        await engine.dispose()
