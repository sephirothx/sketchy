"""Runtime values an administrator may change without a deploy (#446).

Finding the right value for something that affects how the game *feels* costs
a code change and a deploy today, which is enough friction that it mostly does
not happen. The motivating case is the drawer's flush interval: the bandwidth
curve says to raise it, and looking at a viewer's screen says otherwise, at a
tolerance no benchmark would have found. That answer is also unlikely to be
universal - a LAN game and a throttled mobile room do not obviously want the
same number.

Two things about the shape here are load-bearing.

**Values are read through the registry, not imported from it.** Several of the
constants this replaces were pulled into other modules by name -
`from app.game import TURN_RESULTS_SECONDS` - which binds the number at import,
so assigning the module attribute later changes nothing at all. A tunable that
looks mutable and silently is not is worse than an honest constant, so every
entry names a `read`/`write` pair and callers ask at the moment they need the
value.

**Bounds live with whoever owns the value.** The command budgets already carry
their own defaults, limits and prose (`app/handlers/budgets.py`), so their
entries delegate rather than restate them: a bound written down twice is a
bound that will disagree with itself.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import logging
import math
import os

logger = logging.getLogger("sketchy.runtime_settings")

# The `app_config` namespace these are stored under. Prefixed so the table's
# other rows - the auto-generated `ip_hash_secret`, the maintenance flag - are
# not swept up by a prefix read.
CONFIG_PREFIX = "tunable."

SERVER = "server"
CLIENT = "client"


class TunableError(ValueError):
    """A value this registry refuses. The message is written for an operator."""


@dataclass(frozen=True)
class Tunable:
    """One value, what it trades off, and how to reach it at runtime.

    `read` and `write` are the whole point: the registry never holds the live
    value itself, it holds the pair of callables that reach wherever the value
    actually lives. That keeps one number in one place, so a handler consulting
    its own service and the panel reporting a value cannot drift apart.
    """

    name: str
    default: float
    minimum: float
    maximum: float
    unit: str
    description: str
    read: Callable[[], float]
    write: Callable[[float], None]
    audience: str = SERVER
    # Integers everywhere except the drain window, which has always been a
    # float and is documented in seconds with a fractional part allowed.
    integral: bool = True
    # The variable that supplied the boot default, when one did. Reported so a
    # panel can say where a value came from, and so an operator who set it in
    # the environment is told why their number is not the one in force.
    env_var: str | None = None

    def coerce(self, value: object) -> float:
        """Read an operator's input as this tunable's kind of number."""
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise TunableError(f"{self.name} must be a number")
        try:
            number = float(value)
        except (ValueError, OverflowError) as error:
            # OverflowError as well as ValueError: JSON has no integer bound
            # and Python's has none either, so `10**309` parses fine and only
            # falls over on the way to a float. Both are the same mistake from
            # an operator's side, and both deserve the same bounded answer.
            raise TunableError(f"{self.name} must be a number") from error
        # Before any arithmetic. `float()` accepts "nan" and "inf" happily, and
        # every use after this point - the bounds comparison, the integer
        # conversion, the frames-per-window division in a joint constraint -
        # either raises or quietly answers nonsense on one of them. A refusal
        # here is a bounded 400 rather than a traceback.
        if not math.isfinite(number):
            raise TunableError(f"{self.name} must be a finite number")
        if self.integral:
            if number != int(number):
                raise TunableError(f"{self.name} must be a whole number")
            return int(number)
        return number

    def check(self, value: float) -> None:
        """Refuse a value outside the bounds, in the units it was given in."""
        if not self.minimum <= value <= self.maximum:
            raise TunableError(
                f"{self.name} must be between {_plain(self.minimum)} and "
                f"{_plain(self.maximum)}"
            )


def _plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


@dataclass(frozen=True)
class JointConstraint:
    """A rule about values that each pass their own bounds but not together.

    The drawing budget and the client's flush interval are one setting wearing
    two hats: the interval decides how many frames a legitimate drawer sends,
    and the budget decides how many the server will accept from one. Either
    number is reasonable alone and the pair can still refuse ordinary drawing,
    and until this panel existed there was no way to set them independently -
    so there was nothing to check.
    """

    names: tuple[str, ...]
    check: Callable[[Mapping[str, float]], None]


class RuntimeSettings:
    """The tunables in force, where they came from, and how to change them.

    Precedence is compiled default, then the environment, then a stored value -
    stored last because a deployment that pins a number in its environment is
    exactly the one that most wants to try a different number without a
    redeploy. The environment keeps configuring the value a fresh database
    starts at, which is what the requirements naming those variables ask for;
    it just stops being the last word.
    """

    def __init__(
        self,
        tunables: Sequence[Tunable],
        *,
        constraints: Sequence[JointConstraint] = (),
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._tunables: dict[str, Tunable] = {item.name: item for item in tunables}
        if len(self._tunables) != len(tunables):
            raise ValueError("two tunables share a name")
        for constraint in constraints:
            unknown = set(constraint.names) - set(self._tunables)
            if unknown:
                raise ValueError(f"constraint names no such tunable: {sorted(unknown)}")
        self._constraints = tuple(constraints)
        values = os.environ if environ is None else environ
        self._boot: dict[str, float] = {}
        self._from_env: set[str] = set()
        self._stored: set[str] = set()
        # Rows that exist and are not in force, because this release refuses
        # the value they hold. Tracked because they are still rows: they must
        # be visible, clearable, and must not quietly become active again if a
        # later release widens the bound they fell outside of.
        self._rejected: set[str] = set()
        for item in self._tunables.values():
            self._boot[item.name] = self._boot_value(item, values)
            item.write(self._boot[item.name])

    def _boot_value(self, item: Tunable, values: Mapping[str, str]) -> float:
        """The value before anything stored: the environment, or the default."""
        if item.env_var is None:
            return item.default
        raw = values.get(item.env_var, "").strip()
        if not raw:
            return item.default
        try:
            candidate = item.coerce(raw)
            item.check(candidate)
        except TunableError as error:
            # Deliberately not fatal. These variables have always been
            # forgiving, and refusing to boot over a mistyped ceiling would
            # turn a tuning mistake into an outage.
            logger.warning(
                "%s: %s; using %s", item.env_var, error, _plain(item.default)
            )
            return item.default
        self._from_env.add(item.name)
        return candidate

    # ---------------------------------------------------------------- reading

    def __contains__(self, name: object) -> bool:
        return name in self._tunables

    def names(self) -> Iterable[str]:
        return self._tunables.keys()

    def tunable(self, name: str) -> Tunable:
        item = self._tunables.get(name)
        if item is None:
            raise TunableError(f"unknown setting: {name}")
        return item

    def value(self, name: str) -> float:
        return self.tunable(name).read()

    def boot_value(self, name: str) -> float:
        """What this process started this setting at, before anything stored.

        The endpoint needs it to tell a stored row from a redundant one: a
        value equal to the boot value has nothing to persist, and writing it
        anyway would pin the setting against a later environment change.
        """
        self.tunable(name)
        return self._boot[name]

    def is_stored(self, name: str) -> bool:
        """Whether a persisted row exists for this setting, in force or not."""
        self.tunable(name)
        return name in self._stored or name in self._rejected

    def is_rejected(self, name: str) -> bool:
        """Whether a stored row exists that this release will not apply."""
        self.tunable(name)
        return name in self._rejected

    def source(self, name: str) -> str:
        """Where the setting's override stands, for a panel to show.

        A refused row still counts as stored: it exists, and reporting it as
        default or environment is what left it unreachable. `override_rejected`
        in `describe()` says whether the stored value is the one running.
        """
        if self.is_stored(name):
            return "stored"
        if name in self._from_env:
            return "environment"
        return "default"

    def describe(self) -> list[dict]:
        """Every tunable with its value, bounds, origin and purpose.

        Plain field names rather than wire names, following the budgets policy
        this delegates to: the endpoint owns its own camelCase, and inventing
        keys here that no client reads would be a contract with nobody.
        """
        return [
            {
                "name": item.name,
                "value": item.read(),
                "default": item.default,
                "boot_value": self._boot[item.name],
                "minimum": item.minimum,
                "maximum": item.maximum,
                "unit": item.unit,
                # Whether the value space is whole numbers. A panel needs it to
                # build a control that can express what the bounds allow: a
                # number input stepping by one cannot reach 12.5 seconds.
                "integral": item.integral,
                "audience": item.audience,
                "description": item.description,
                "env_var": item.env_var,
                "source": self.source(item.name),
                # A row this release refuses. The value above is what is
                # actually running; without saying so, a panel would report a
                # setting as overridden and show the default beside it.
                "override_rejected": item.name in self._rejected,
            }
            for item in self._tunables.values()
        ]

    # ---------------------------------------------------------------- writing

    def validate(
        self,
        changes: Mapping[str, object] | None = None,
        resets: Iterable[str] = (),
    ) -> dict[str, float]:
        """What these changes would come to, or the reason they cannot.

        Everything is checked before anything is written, and the whole set is
        checked at once. Both matter for a request that carries several values:
        a change refused halfway through would leave the server running a
        configuration nobody chose, and a pair that only holds together - a
        faster cadence and the larger budget that admits it - is refused if the
        two are measured one at a time against what is still in force.
        """
        wanted: dict[str, float] = {}
        for name in resets:
            self.tunable(name)
            wanted[name] = self._boot[name]
        for name, value in (changes or {}).items():
            item = self.tunable(name)
            number = item.coerce(value)
            item.check(number)
            wanted[name] = number
        self._check_jointly(wanted)
        return wanted

    def apply(
        self,
        values: Mapping[str, float],
        *,
        stored: bool = True,
    ) -> None:
        """Write values that have already been validated together.

        `stored` records whether these names now have a persisted row, and it
        is the caller's answer rather than something inferred here. Inferring
        it from "the value differs from the boot value" was wrong in a way
        that hid itself: a row whose value later coincided with a changed boot
        value stopped being reported as stored, so the panel offered no way to
        clear it - and the next time the environment moved, the forgotten row
        won. Row existence and numeric equality are different facts.
        """
        for name, number in values.items():
            self._tunables[name].write(number)
            self._rejected.discard(name)
            if stored:
                self._stored.add(name)
            else:
                self._stored.discard(name)

    def set(self, name: str, value: object, *, stored: bool = True) -> float:
        """Apply one change, refusing anything the runtime could not live with."""
        wanted = self.validate({name: value})
        self.apply(wanted, stored=stored)
        return wanted[name]

    def reset(self, name: str) -> float:
        """Put a value back to what this process booted with, and unstore it."""
        wanted = self.validate(resets=[name])
        self.apply(wanted, stored=False)
        return wanted[name]

    def apply_stored(self, rows: Mapping[str, str]) -> None:
        """Adopt what was persisted, at startup, as one set rather than in turn.

        Applied together on purpose. A pair that only makes sense as a pair -
        a faster flush interval and the larger drawing budget that admits it -
        is refused if it arrives one value at a time, because the first change
        is measured against the second's boot value. Whichever order the rows
        came back in would decide whether the deployment starts with the
        settings it was left with.

        One bad row must also not cost every other one: a stored value can fall
        out of bounds legitimately, when a release tightens a maximum around a
        number already in the table, and the right answer is that value back at
        its default plus a line in the log.
        """
        accepted: dict[str, float] = {}
        for name, raw in rows.items():
            item = self._tunables.get(name)
            if item is None:
                logger.warning("stored setting %s is not known; ignoring it", name)
                continue
            try:
                number = item.coerce(raw)
                item.check(number)
            except TunableError as error:
                logger.warning(
                    "stored setting %s: %s; using %s",
                    name,
                    error,
                    _plain(self._boot[name]),
                )
                # The row is remembered even though the value is not applied,
                # so it can be seen and cleared. Forgetting it left an
                # override the panel called absent, that no reset could reach,
                # and that would come back the day a release widened the bound
                # it fell outside of.
                self._rejected.add(name)
                continue
            accepted[name] = number

        for constraint in self._constraints:
            if not accepted.keys() & set(constraint.names):
                continue
            try:
                constraint.check(self._prospective(accepted))
            except TunableError as error:
                logger.warning(
                    "stored settings %s: %s; using boot values for them",
                    ", ".join(sorted(constraint.names)),
                    error,
                )
                for name in constraint.names:
                    if accepted.pop(name, None) is not None:
                        self._rejected.add(name)

        self.apply(accepted)

    def _check_jointly(self, changes: Mapping[str, float]) -> None:
        """Refuse values that are individually fine and wrong beside each other."""
        for constraint in self._constraints:
            if not changes.keys() & set(constraint.names):
                continue
            constraint.check(self._prospective(changes))

    def _prospective(self, changes: Mapping[str, float]) -> dict[str, float]:
        """What every value would be if these changes were applied."""
        return {name: changes.get(name, item.read()) for name, item in self._tunables.items()}
