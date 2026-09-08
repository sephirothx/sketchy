"""What a password guess meets before the password is ever checked.

Login used to be limited by address alone, which is the one key a distributed
attack does not have to reuse. A botnet with ten thousand hosts could spend
ten attempts from each against a single account and never fill a bucket, so
the limit that existed protected the server's CPU rather than anybody's
account (#468, PR-17).

Three keys are counted here, because each answers a question the others
cannot:

- **the account**, so attempts against one username add up no matter how many
  addresses they arrive from. This is the one that stops credential stuffing;
- **the address**, so one host cannot work through a list of usernames. This
  is the one that stops a single machine spraying;
- **the deployment**, so a spray across many usernames from many addresses -
  where neither of the other two keys repeats - still meets a ceiling.

All three count **failures only**, and a success refunds nothing because
nothing was charged. That is what makes the limits safe to set low: a family
sharing an address, or a household where three people sign in every evening,
never touches them, because signing in correctly costs nothing. The old
limiter charged every attempt, which is why its ceiling had to be loose
enough to be worth little.

On top of the windows, one account's consecutive failures buy an increasing
lockout: the same ten guesses spread over an afternoon are a slow attack, and
a fixed window forgets them between each one. `auth_login_lockouts` remembers
across windows and is cleared by one correct password.

The account key is a keyed hash of the lowercased username, never the username
(R-PRIV-09's reasoning applied to a name rather than an address): these tables
must not become a list of which accounts exist, or of which are under attack.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import PersistentRateLimiter, keyed_client_hash
from app.db.models import AuthLoginLockout


# Consecutive failures on one account before it starts backing off, and what
# each further failure costs. Three is chosen so an ordinary person mistyping
# a password twice notices nothing at all.
LOCKOUT_AFTER_FAILURES = 3
LOCKOUT_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)
# A lockout row that has not been touched in a day is a finished attack, and
# the count behind it should not follow somebody for a week.
LOCKOUT_FORGET_AFTER = timedelta(days=1)

GLOBAL_LOGIN_KEY = "all"


def _limit(name: str, default: int) -> int:
    """Read a ceiling from the environment, falling back to the default."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass(frozen=True)
class LoginVerdict:
    """Whether an attempt may be made, and when to come back if not."""

    allowed: bool
    retry_after_seconds: int = 0

    @property
    def message(self) -> str:
        """One sentence, saying nothing about whether the account exists.

        Deliberately the same words whichever key refused, and whether or not
        the username is real. A message that distinguished "this account is
        locked" from "this address has tried too often" would answer the
        question R-AUTH-09 exists to leave unanswered.
        """
        return "Too many attempts. Please wait and try again."


class LoginGuard:
    """The three counters and the lockout, behind one pair of calls."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._address = PersistentRateLimiter(
            session_factory,
            scope="login",
            limit=_limit("AUTH_LOGIN_LIMIT", 10),
            window_seconds=300,
        )
        self._account = PersistentRateLimiter(
            session_factory,
            scope="login_account",
            limit=_limit("AUTH_LOGIN_ACCOUNT_LIMIT", 10),
            window_seconds=900,
            clock=clock,
        )
        # Generous, and a last resort rather than a first line: it is the only
        # one of the three an attacker can saturate on purpose to make logins
        # fail for everybody, so it sits far above any honest failure rate this
        # server would produce. Set `AUTH_LOGIN_GLOBAL_LIMIT=0` to switch it
        # off on a deployment that would rather take the spray than the risk.
        self._global_limit = _limit("AUTH_LOGIN_GLOBAL_LIMIT", 500)
        self._deployment = PersistentRateLimiter(
            session_factory,
            scope="login_global",
            limit=self._global_limit or 1,
            window_seconds=300,
            clock=clock,
        )

    async def _account_key(self, username: str) -> str:
        return await keyed_client_hash(
            self._session_factory, f"login:{(username or '').strip().lower()}"
        )

    async def check(self, *, username: str, address: str) -> LoginVerdict:
        """Ask all three counters and the lockout, spending nothing.

        Ordered cheapest-refusal-first only by accident; every one of them is
        a single indexed read, and all of them are asked because a caller
        refused by two keys should not learn which by how long the answer
        took.
        """
        now = self._clock()
        locked_for = await self._lockout_remaining(username, now=now)
        if locked_for > 0:
            return LoginVerdict(allowed=False, retry_after_seconds=locked_for)
        if not await self._account.peek(await self._account_key(username)):
            return LoginVerdict(allowed=False, retry_after_seconds=900)
        if not await self._address.peek(address):
            return LoginVerdict(allowed=False, retry_after_seconds=300)
        if self._global_limit and not await self._deployment.peek(GLOBAL_LOGIN_KEY):
            return LoginVerdict(allowed=False, retry_after_seconds=300)
        return LoginVerdict(allowed=True)

    async def note_failure(self, *, username: str, address: str) -> None:
        """Charge every counter, and lengthen this account's backoff."""
        await self._account.check(await self._account_key(username))
        await self._address.check(address)
        if self._global_limit:
            await self._deployment.check(GLOBAL_LOGIN_KEY)
        await self._record_lockout_failure(username)

    async def note_success(self, *, username: str) -> None:
        """Forget this account's consecutive failures.

        Only the lockout is cleared. The windows are not, because they count
        what happened rather than who it happened to: one correct password
        does not make the two hundred wrong ones before it honest.
        """
        key_hash = await self._account_key(username)
        async with self._session_factory() as database:
            async with database.begin():
                await database.execute(
                    delete(AuthLoginLockout).where(
                        AuthLoginLockout.key_hash == key_hash
                    )
                )

    async def _lockout_remaining(self, username: str, *, now: datetime) -> int:
        key_hash = await self._account_key(username)
        async with self._session_factory() as database:
            record = await database.get(AuthLoginLockout, key_hash)
            if record is None or record.locked_until is None:
                return 0
            if record.locked_until <= now:
                return 0
            return max(1, int((record.locked_until - now).total_seconds()))

    async def _record_lockout_failure(self, username: str) -> None:
        """One more consecutive failure, and the wait it now costs.

        Read-then-write rather than a conditional statement, unlike the
        buckets: two failures racing here can only under-count by one, and
        under-counting a lockout by one attempt is not a hole - the windows
        above are the ceiling that has to be exact.
        """
        key_hash = await self._account_key(username)
        now = self._clock()
        for _ in range(2):
            async with self._session_factory() as database:
                async with database.begin():
                    record = await database.get(AuthLoginLockout, key_hash)
                    if record is None:
                        try:
                            database.add(
                                AuthLoginLockout(
                                    key_hash=key_hash,
                                    consecutive_failures=1,
                                    locked_until=None,
                                    updated_at=now,
                                )
                            )
                            await database.flush()
                        except IntegrityError:
                            continue
                        return
                    stale = now - record.updated_at >= LOCKOUT_FORGET_AFTER
                    failures = 1 if stale else record.consecutive_failures + 1
                    record.consecutive_failures = failures
                    record.updated_at = now
                    record.locked_until = _locked_until(failures, now)
                    return

    async def forget_expired_lockouts(self, *, before: datetime | None = None) -> int:
        """Drop rows no longer holding anybody back, so the table stays small."""
        cutoff = (before or self._clock()) - LOCKOUT_FORGET_AFTER
        async with self._session_factory() as database:
            async with database.begin():
                removed = await database.execute(
                    delete(AuthLoginLockout).where(
                        AuthLoginLockout.updated_at <= cutoff
                    )
                )
                return int(removed.rowcount or 0)


def _locked_until(failures: int, now: datetime) -> datetime | None:
    """How long this many consecutive failures buys, or nothing yet."""
    if failures < LOCKOUT_AFTER_FAILURES:
        return None
    step = min(failures - LOCKOUT_AFTER_FAILURES, len(LOCKOUT_BACKOFF) - 1)
    return now + LOCKOUT_BACKOFF[step]


async def count_open_lockouts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> int:
    """How many accounts are being held back right now, for the operator view."""
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        rows = await database.execute(
            select(AuthLoginLockout.key_hash).where(
                AuthLoginLockout.locked_until > checked_at
            )
        )
        return len(rows.all())
