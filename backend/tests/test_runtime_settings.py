"""What an administrator may change at runtime, and what the registry refuses.

The registry exists because several of the values it replaces could not simply
be made mutable: `from app.game import TURN_RESULTS_SECONDS` binds the number
at import, so assigning the module attribute afterwards changes nothing. These
tests pin the behaviour that makes the indirection worth its cost - precedence,
bounds, joint constraints, and a stored set that survives a restart without one
bad row taking the others down with it.
"""

import logging

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import AppConfig, Base
from app.services import config_store
from app.services.runtime_settings import (
    CLIENT,
    JointConstraint,
    RuntimeSettings,
    Tunable,
    TunableError,
)


class Cell:
    """Somewhere for a tunable to live, standing in for a real service."""

    def __init__(self, value: float = 0) -> None:
        self.value = value

    def read(self) -> float:
        return self.value

    def write(self, value: float) -> None:
        self.value = value


def a_tunable(cell: Cell, **overrides) -> Tunable:
    fields = {
        "name": "widgets",
        "default": 10,
        "minimum": 1,
        "maximum": 100,
        "unit": "widgets",
        "description": "How many widgets.",
        "read": cell.read,
        "write": cell.write,
    }
    fields.update(overrides)
    return Tunable(**fields)


# ------------------------------------------------------------------ precedence


def test_a_tunable_starts_at_its_compiled_default():
    cell = Cell()
    settings = RuntimeSettings([a_tunable(cell)], environ={})
    assert cell.value == 10
    assert settings.value("widgets") == 10
    assert settings.source("widgets") == "default"


def test_the_environment_supplies_the_boot_value():
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, env_var="WIDGET_LIMIT")], environ={"WIDGET_LIMIT": "42"}
    )
    assert cell.value == 42
    assert settings.source("widgets") == "environment"


def test_a_stored_value_overrides_the_environment():
    """The deployment that pinned a number is the one that wants to try another.

    R-SHUT-03 and the room-ceiling requirements keep their variables: the
    environment still decides what a fresh database boots at. It simply stops
    being the last word once an administrator has said otherwise.
    """
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, env_var="WIDGET_LIMIT")], environ={"WIDGET_LIMIT": "42"}
    )
    settings.apply_stored({"widgets": "7"})
    assert cell.value == 7
    assert settings.source("widgets") == "stored"


def test_resetting_returns_to_the_environment_rather_than_the_default():
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, env_var="WIDGET_LIMIT")], environ={"WIDGET_LIMIT": "42"}
    )
    settings.set("widgets", 7)
    assert settings.reset("widgets") == 42
    assert cell.value == 42
    assert settings.source("widgets") == "environment"


def test_an_unreadable_environment_value_warns_rather_than_refusing_to_boot(caplog):
    cell = Cell()
    with caplog.at_level(logging.WARNING):
        settings = RuntimeSettings(
            [a_tunable(cell, env_var="WIDGET_LIMIT")], environ={"WIDGET_LIMIT": "lots"}
        )
    assert cell.value == 10
    assert settings.source("widgets") == "default"
    assert "WIDGET_LIMIT" in caplog.text


def test_an_out_of_bounds_environment_value_falls_back_to_the_default():
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, env_var="WIDGET_LIMIT")], environ={"WIDGET_LIMIT": "5000"}
    )
    assert cell.value == 10
    assert settings.source("widgets") == "default"


# ---------------------------------------------------------------------- bounds


@pytest.mark.parametrize("value", [0, 101, -3])
def test_a_value_outside_the_bounds_is_refused(value):
    cell = Cell()
    settings = RuntimeSettings([a_tunable(cell)], environ={})
    with pytest.raises(TunableError, match="between 1 and 100"):
        settings.set("widgets", value)
    assert cell.value == 10


@pytest.mark.parametrize("value", ["lots", None, True, [5]])
def test_a_value_that_is_not_a_number_is_refused(value):
    cell = Cell()
    settings = RuntimeSettings([a_tunable(cell)], environ={})
    with pytest.raises(TunableError, match="must be a number"):
        settings.set("widgets", value)


def test_an_integral_tunable_refuses_a_fraction():
    cell = Cell()
    settings = RuntimeSettings([a_tunable(cell)], environ={})
    with pytest.raises(TunableError, match="whole number"):
        settings.set("widgets", 10.5)


def test_a_fractional_tunable_keeps_its_fraction():
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, integral=False, minimum=0, maximum=300)], environ={}
    )
    assert settings.set("widgets", 12.5) == 12.5
    assert cell.value == 12.5


def test_an_unknown_setting_is_refused_by_name():
    settings = RuntimeSettings([a_tunable(Cell())], environ={})
    with pytest.raises(TunableError, match="unknown setting: sprockets"):
        settings.set("sprockets", 1)


def test_two_tunables_may_not_share_a_name():
    with pytest.raises(ValueError, match="share a name"):
        RuntimeSettings([a_tunable(Cell()), a_tunable(Cell())], environ={})


# ------------------------------------------------------------ what a panel reads


def test_describe_reports_the_value_its_bounds_and_where_it_came_from():
    cell = Cell()
    settings = RuntimeSettings(
        [a_tunable(cell, audience=CLIENT, env_var="WIDGET_LIMIT")],
        environ={"WIDGET_LIMIT": "42"},
    )
    (described,) = settings.describe()
    assert described == {
        "name": "widgets",
        "value": 42,
        "default": 10,
        "boot_value": 42,
        "minimum": 1,
        "maximum": 100,
        "unit": "widgets",
        "audience": "client",
        "description": "How many widgets.",
        "env_var": "WIDGET_LIMIT",
        "source": "environment",
    }


# ----------------------------------------------------------- joint constraints


def _paired_registry(frames: Cell, budget: Cell) -> RuntimeSettings:
    """A miniature of the flush-interval / drawing-budget pair."""

    def enough_budget(values):
        if values["frames"] > values["budget"]:
            raise TunableError(
                f"a budget of {int(values['budget'])} refuses {int(values['frames'])} frames"
            )

    return RuntimeSettings(
        [
            a_tunable(frames, name="frames", default=25, minimum=1, maximum=200),
            a_tunable(budget, name="budget", default=100, minimum=1, maximum=200),
        ],
        constraints=[JointConstraint(("frames", "budget"), enough_budget)],
        environ={},
    )


def test_two_values_each_within_bounds_can_still_be_refused_together():
    frames, budget = Cell(), Cell()
    settings = _paired_registry(frames, budget)
    with pytest.raises(TunableError, match="refuses 150 frames"):
        settings.set("frames", 150)
    assert frames.value == 25


def test_the_constraint_is_checked_from_either_side():
    frames, budget = Cell(), Cell()
    settings = _paired_registry(frames, budget)
    settings.set("frames", 90)
    with pytest.raises(TunableError, match="refuses 90 frames"):
        settings.set("budget", 50)
    assert budget.value == 100


def test_a_stored_pair_is_adopted_together_rather_than_in_turn():
    """Neither order of the same two rows may decide whether they are kept.

    Applied one at a time, a faster cadence is measured against the budget the
    process booted with, so a pair an administrator set successfully would be
    thrown away on the next restart - and which of the two survived would
    depend on the order the rows came back in.
    """
    for rows in (
        {"frames": "180", "budget": "200"},
        {"budget": "200", "frames": "180"},
    ):
        frames, budget = Cell(), Cell()
        settings = _paired_registry(frames, budget)
        settings.apply_stored(rows)
        assert (frames.value, budget.value) == (180, 200)


def test_a_stored_pair_that_cannot_hold_together_falls_back_to_boot(caplog):
    frames, budget = Cell(), Cell()
    settings = _paired_registry(frames, budget)
    with caplog.at_level(logging.WARNING):
        settings.apply_stored({"frames": "180", "budget": "40"})
    assert (frames.value, budget.value) == (25, 100)
    assert settings.source("frames") == "default"


# ---------------------------------------------------------------- stored rows


def test_one_unusable_stored_row_does_not_cost_the_others(caplog):
    """A release that tightens a maximum leaves an old number behind it."""
    widgets, sprockets = Cell(), Cell()
    settings = RuntimeSettings(
        [
            a_tunable(widgets, name="widgets"),
            a_tunable(sprockets, name="sprockets", default=3),
        ],
        environ={},
    )
    with caplog.at_level(logging.WARNING):
        settings.apply_stored({"widgets": "5000", "sprockets": "9"})
    assert widgets.value == 10
    assert sprockets.value == 9
    assert "widgets" in caplog.text


def test_a_stored_row_for_a_setting_that_no_longer_exists_is_ignored(caplog):
    cell = Cell()
    settings = RuntimeSettings([a_tunable(cell)], environ={})
    with caplog.at_level(logging.WARNING):
        settings.apply_stored({"gadgets": "4"})
    assert cell.value == 10
    assert "gadgets" in caplog.text


# --------------------------------------------------------------- the store



async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_stored_values_survive_a_restart():
    """The whole point of persisting: the next process starts where this one left off."""
    engine, factory = await _database()
    try:
        async with factory() as session:
            async with session.begin():
                await config_store.put(session, "tunable.widgets", "7")

        cell = Cell()
        settings = RuntimeSettings([a_tunable(cell, env_var="WIDGET_LIMIT")], environ={})
        settings.apply_stored(await config_store.read_prefixed(factory, "tunable."))
        assert cell.value == 7
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_writing_the_same_key_twice_replaces_rather_than_duplicates():
    engine, factory = await _database()
    try:
        async with factory() as session:
            async with session.begin():
                await config_store.put(session, "tunable.widgets", "7")
                await config_store.put(session, "tunable.widgets", "9")
        assert await config_store.read_prefixed(factory, "tunable.") == {"widgets": "9"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_prefix_read_leaves_the_tables_other_rows_alone():
    """`app_config` also holds the auto-generated IP hashing secret."""
    engine, factory = await _database()
    try:
        async with factory() as session:
            async with session.begin():
                session.add(AppConfig(key="ip_hash_secret", value="not-a-setting"))
                await config_store.put(session, "tunable.widgets", "7")
        assert await config_store.read_prefixed(factory, "tunable.") == {"widgets": "7"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dropping_a_key_forgets_it():
    engine, factory = await _database()
    try:
        async with factory() as session:
            async with session.begin():
                await config_store.put(session, "tunable.widgets", "7")
        async with factory() as session:
            async with session.begin():
                await config_store.drop(session, "tunable.widgets")
        assert await config_store.read_prefixed(factory, "tunable.") == {}
    finally:
        await engine.dispose()
