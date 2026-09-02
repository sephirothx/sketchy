"""Which runtime values an administrator may change, and what each trades off.

The registry in `runtime_settings.py` is the mechanism; this is the list. It is
deliberately a list rather than "every constant", because each value added is
one that can be set wrong in production, and a configuration surface that has
drifted from its defaults is harder to reason about than a constant. Three
kinds are kept off it on purpose:

* **Abuse backstops** - the authentication limits, the report submission
  limits, the canvas and replay ceilings. Something that can be loosened at
  runtime is something an attacker benefits from having loosened, and none of
  them have the property that motivated this panel: a value only looking at the
  running game can settle.
* **Anything that can change a score.** Every completed game freezes a rule
  snapshot and `SCORING_RULES_VERSION` exists so that scores stay comparable.
* **Values the frontend duplicates**, such as the player-count range and the
  drawing-time options. Those are a wire contract shared with the client, and
  changing one side alone makes the two disagree rather than making the server
  configurable.

A tunable is also not a test setting. E2E fast-forwards the page's own clock
(R-ENG-10) and must never reach for one of these to make itself faster.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import partial

from app.client_config import ClientConfig
from app.deployment import DEFAULT_SHUTDOWN_DRAIN_SECONDS, MAX_SHUTDOWN_DRAIN_SECONDS
from app.flow_timing import FlowTiming
from app.handlers.budgets import CommandBudgetPolicy
from app.services.room_quotas import (
    DEFAULT_CREATIONS_PER_HOUR,
    DEFAULT_GLOBAL_ROOMS,
    DEFAULT_JOINS_PER_SOCKET,
    DEFAULT_PER_ACCOUNT_ROOMS,
    DEFAULT_PROMPT_CHARACTERS,
    DEFAULT_SOCKETS,
    DEFAULT_SPECTATORS_PER_ROOM,
    DEFAULT_TAKEOVERS_PER_SEAT,
    RoomCapacityService,
    RoomQuotaService,
)
from app.services.runtime_settings import (
    CLIENT,
    SERVER,
    JointConstraint,
    RuntimeSettings,
    Tunable,
    TunableError,
)
from app.services.shutdown import ShutdownCoordinator


def budget_tunables(policy: CommandBudgetPolicy) -> list[Tunable]:
    """The six per-caller command budgets, described by the policy itself.

    Nothing here restates a bound or a description. `BudgetClass` already
    carries both, sized against what the client actually does, and a bound
    written down in two places is one that will eventually disagree with
    itself - in the direction of refusing ordinary play, since that is the side
    a stale copy tends to be stricter on.
    """
    tunables = []
    for described in policy.describe():
        name = described["name"]
        window = described["window_seconds"]
        tunables.append(
            Tunable(
                name=f"budget.{name}",
                default=described["default_limit"],
                minimum=described["minimum"],
                maximum=described["maximum"],
                unit=f"commands per {_seconds(window)}s",
                description=described["description"],
                read=partial(policy.limit_of, name),
                write=partial(_set_budget, policy, name),
            )
        )
    return tunables


def _set_budget(policy: CommandBudgetPolicy, name: str, limit: float) -> None:
    policy.set_limit(name, int(limit))


def _seconds(window: float) -> str:
    return str(int(window)) if float(window).is_integer() else str(window)


def _attribute(holder: object, name: str) -> tuple:
    """A read/write pair reaching one attribute of a live object."""
    return (
        lambda: getattr(holder, name),
        lambda value: setattr(holder, name, value),
    )


def _number(
    holder: object,
    attribute: str,
    *,
    name: str,
    default: float,
    minimum: float,
    maximum: float,
    unit: str,
    description: str,
    env_var: str | None = None,
    integral: bool = True,
    audience_: str = SERVER,
) -> Tunable:
    read, write = _attribute(holder, attribute)
    return Tunable(
        name=name,
        default=default,
        minimum=minimum,
        maximum=maximum,
        unit=unit,
        description=description,
        read=read,
        write=write,
        env_var=env_var,
        integral=integral,
        audience=audience_,
    )


def ceiling_tunables(
    quotas: RoomQuotaService, capacity: RoomCapacityService
) -> list[Tunable]:
    """How much of one process a room, an account or a socket may occupy.

    These already read the environment, and they keep doing so - the variable
    still decides what a fresh deployment boots at. What changes is that the
    number can be moved while players are in the building, which is when the
    operator finds out whether it was the right one.
    """
    return [
        _number(
            quotas, "global_rooms",
            name="rooms.global_limit", default=DEFAULT_GLOBAL_ROOMS,
            minimum=1, maximum=5_000, unit="rooms",
            env_var="ROOM_GLOBAL_LIMIT",
            description=(
                "Live rooms this process will hold at once. Four times the "
                "documented validation target, so the target is not also the wall."
            ),
        ),
        _number(
            quotas, "per_account_rooms",
            name="rooms.per_account_limit", default=DEFAULT_PER_ACCOUNT_ROOMS,
            minimum=1, maximum=100, unit="rooms",
            env_var="ROOM_PER_ACCOUNT_LIMIT",
            description=(
                "Rooms one account may have open. Enough for a host running a "
                "couple and setting up a third; far below what a script wants."
            ),
        ),
        _number(
            quotas, "creations_per_hour",
            name="rooms.creations_per_hour", default=DEFAULT_CREATIONS_PER_HOUR,
            minimum=1, maximum=1_000, unit="rooms per hour",
            env_var="ROOM_CREATE_LIMIT",
            description=(
                "How often one account may open a room. An attempt that opens "
                "no room is given back rather than spent."
            ),
        ),
        _number(
            quotas, "prompt_characters",
            name="rooms.prompt_character_limit", default=DEFAULT_PROMPT_CHARACTERS,
            minimum=64 * 1024, maximum=64 * 1024 * 1024, unit="characters",
            env_var="ROOM_PROMPT_CHARACTER_LIMIT",
            description=(
                "Custom-prompt text held across every live room at once. The "
                "per-room ceiling bounds one room; this bounds their sum."
            ),
        ),
        _number(
            capacity, "spectators_per_room",
            name="rooms.spectators_per_room", default=DEFAULT_SPECTATORS_PER_ROOM,
            # One rather than zero, matching what the environment reader has
            # always accepted: turning spectating off entirely would be a new
            # capability, not a tuning of an existing one.
            minimum=1, maximum=100, unit="spectators",
            env_var="ROOM_SPECTATOR_LIMIT",
            description=(
                "Watchers one room admits. Watching is cheaper than playing but "
                "not free: every spectator is another recipient of every broadcast."
            ),
        ),
        _number(
            capacity, "sockets",
            name="rooms.socket_limit", default=DEFAULT_SOCKETS,
            minimum=10, maximum=20_000, unit="sockets",
            env_var="SOCKET_LIMIT",
            description=(
                "Connections this process admits. An arrival beyond it is told "
                "and then closed, never refused at the handshake."
            ),
        ),
        _number(
            capacity, "joins_per_socket_limit",
            name="rooms.joins_per_socket", default=DEFAULT_JOINS_PER_SOCKET,
            minimum=1, maximum=500, unit="joins per minute",
            env_var="ROOM_JOIN_LIMIT",
            description=(
                "Seating joins one socket may make in a minute. Confirming a "
                "seat already held is free, so a heartbeat cannot lock anyone out."
            ),
        ),
        _number(
            capacity, "takeovers_per_seat_limit",
            name="rooms.takeovers_per_seat", default=DEFAULT_TAKEOVERS_PER_SEAT,
            minimum=1, maximum=500, unit="takeovers per minute",
            env_var="ROOM_TAKEOVER_LIMIT",
            description=(
                "Rebinds of one seat to a new socket per minute. Keyed by the "
                "seat, which is the part an attacker is not replacing."
            ),
        ),
    ]


def flow_tunables(flow: FlowTiming) -> list[Tunable]:
    """How long each phase of a turn waits.

    The pacing of a game is the clearest case of something only playing one
    can settle, and every one of these is felt by four to sixteen people at
    once rather than measured.
    """
    return [
        _number(
            flow, "choose_prompt_seconds",
            name="turn.choose_prompt_seconds", default=15,
            minimum=5, maximum=60, unit="seconds",
            description=(
                "How long a drawer has to pick a prompt before one is picked "
                "for them. Long enough to read four; short enough not to hold "
                "the room."
            ),
        ),
        _number(
            flow, "turn_results_seconds",
            name="turn.results_seconds", default=5,
            minimum=0, maximum=30, unit="seconds", integral=False,
            env_var="TURN_RESULTS_SECONDS",
            description=(
                "The pause on the turn-results screen. Clients read the length "
                "off the payload, so a shorter one is still a faithful turn."
            ),
        ),
        _number(
            flow, "reconnect_grace_seconds",
            name="turn.reconnect_grace_seconds", default=30,
            minimum=5, maximum=300, unit="seconds",
            description=(
                "How long a disconnected player keeps their seat. Long enough "
                "for a tab switch or a lift; short enough that a room is not "
                "held by somebody who has gone."
            ),
        ),
        _number(
            flow, "restart_vote_seconds",
            name="restart.vote_seconds", default=20,
            minimum=5, maximum=120, unit="seconds",
            description="How long a restart vote stays open before it lapses.",
        ),
        _number(
            flow, "restart_vote_cooldown_seconds",
            name="restart.vote_cooldown_seconds", default=60,
            minimum=0, maximum=600, unit="seconds",
            description=(
                "How long after a vote before another may be called, so a "
                "losing side cannot simply call it again."
            ),
        ),
        _number(
            flow, "restart_delay_seconds",
            name="restart.delay_seconds", default=3,
            minimum=0, maximum=30, unit="seconds", integral=False,
            description=(
                "The pause between a passed vote and the restart, so the room "
                "can read what happened before the board clears."
            ),
        ),
    ]


def shutdown_tunables(shutdown: ShutdownCoordinator) -> list[Tunable]:
    """The grace a planned deployment gives games already in progress."""
    def read() -> float:
        return shutdown.drain_seconds

    return [
        Tunable(
            name="shutdown.drain_seconds",
            default=DEFAULT_SHUTDOWN_DRAIN_SECONDS,
            minimum=0,
            maximum=MAX_SHUTDOWN_DRAIN_SECONDS,
            unit="seconds",
            integral=False,
            env_var="SHUTDOWN_DRAIN_SECONDS",
            description=(
                "How long a planned shutdown waits for live games to finish "
                "before recording the rest as abandoned. Zero abandons them "
                "immediately; the ceiling is what a deployment can wait."
            ),
            read=read,
            write=shutdown.set_drain_seconds,
        )
    ]


def client_tunables(config: ClientConfig) -> list[Tunable]:
    """Cadences the client runs at, which the server decides and ships.

    The flush interval is the one this whole issue came from. Its bounds are
    wide because the right answer is not universal - a LAN game, a mobile room
    on a throttled connection and a deployment paying for egress do not
    obviously want the same number - and the pairing with the drawing budget
    below is what keeps a wide range from producing an unplayable one.
    """
    return [
        _number(
            config, "flush_interval_ms",
            name="client.flush_interval_ms", default=40,
            minimum=10, maximum=200, unit="ms", audience_=CLIENT,
            description=(
                "How long the drawer's queued points wait before going out as "
                "one frame. Bandwidth against stroke smoothness: the drawer "
                "never feels it, but a viewer draws each batch as one "
                "polyline, so a fast curve arrives faceted."
            ),
        ),
    ]


def drawing_headroom(policy: CommandBudgetPolicy) -> JointConstraint:
    """The drawing budget must admit what the flush interval actually produces.

    These are one setting wearing two hats. The interval decides how many
    frames a legitimate drawer sends; the budget decides how many the server
    accepts from one caller. Either number is defensible alone and the pair can
    still refuse ordinary drawing - and until this panel existed there was no
    way to set them independently, so there was nothing to check.

    The factor of two is the budget's own sizing rule, not a new one: a jittery
    connection bunches frames after a stall, so a ceiling at exactly the
    drawer's rate would refuse the catch-up rather than an abuser.
    """
    window = next(
        item["window_seconds"]
        for item in policy.describe()
        if item["name"] == "drawing"
    )

    def check(values: Mapping[str, float]) -> None:
        interval = values["client.flush_interval_ms"]
        limit = values["budget.drawing"]
        produced = window * 1000 / interval
        if limit < produced * 2:
            raise TunableError(
                f"a flush interval of {int(interval)}ms produces "
                f"{produced:.0f} frames per {_seconds(window)}s, which needs a "
                f"drawing budget of at least {produced * 2:.0f}; it is {int(limit)}"
            )

    return JointConstraint(("client.flush_interval_ms", "budget.drawing"), check)


def build_runtime_settings(
    *,
    budgets: CommandBudgetPolicy,
    quotas: RoomQuotaService | None = None,
    capacity: RoomCapacityService | None = None,
    flow: FlowTiming | None = None,
    client: ClientConfig | None = None,
    shutdown: ShutdownCoordinator | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeSettings:
    """Every tunable this process offers, wired to what actually holds it.

    Each group is optional so a test can build the registry around the one
    service it is exercising, rather than standing up the whole process to
    check a bound.
    """
    # Client cadences first: the flush interval is what #446 was opened about,
    # and a panel that buried it under five server ceilings would be answering
    # a different question from the one that was asked.
    tunables: list[Tunable] = []
    constraints = []
    if client is not None:
        tunables.extend(client_tunables(client))
        constraints.append(drawing_headroom(budgets))
    tunables.extend(budget_tunables(budgets))
    if quotas is not None and capacity is not None:
        tunables.extend(ceiling_tunables(quotas, capacity))
    if flow is not None:
        tunables.extend(flow_tunables(flow))
    if shutdown is not None:
        tunables.extend(shutdown_tunables(shutdown))
    return RuntimeSettings(tunables, constraints=constraints, environ=environ)
