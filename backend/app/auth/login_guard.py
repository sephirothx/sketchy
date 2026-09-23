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

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import PersistentRateLimiter, keyed_client_hash
from app.db.models import AuthLoginLockout
from app.services.sweeps import (
    SweepBudget,
    SweepReport,
    delete_in_batches,
    overdue_probe,
    sweep_budget_from_env,
)


# Consecutive failures on one account before it starts backing off, and what
# each further failure costs. Three is chosen so an ordinary person mistyping
# a password twice notices nothing at all.
LOCKOUT_AFTER_FAILURES = 3
# How many password verifications may be in flight at once for one account,
# and for one address (#1001). The windows count failures, and a failure is
# charged after the hash - so a burst that passed every peek together was
# verified in full: sixty concurrent wrong passwords against one account
# were sixty Argon2 runs, against a ceiling of ten. These bound what a peek
# cannot: what is admitted before anything has been charged. Two per
# account is a household signing in at once; four per address is a NAT.
MAX_INFLIGHT_PER_ACCOUNT = 2
MAX_INFLIGHT_PER_ADDRESS = 4
LOCKOUT_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)
# A lockout row that has not been touched in a day is a finished attack, and
# the count behind it should not follow somebody for a week. Enforced by the
# hourly retention sweep (`purge_forgotten_lockouts`), because a failure is
# counted for usernames that do not exist - deliberately, so the answer does
# not say which do - and every distinct name anybody tries leaves a row (#891).
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
        # The ceiling that holds when neither other key repeats. It no longer
        # refuses everybody when it fills - see `check` - so it can sit at a
        # rate an honest deployment might actually reach without that being a
        # denial of service. `AUTH_LOGIN_GLOBAL_LIMIT=0` switches it off.
        self._global_limit = _limit("AUTH_LOGIN_GLOBAL_LIMIT", 500)
        self._deployment = PersistentRateLimiter(
            session_factory,
            scope="login_global",
            limit=self._global_limit or 1,
            window_seconds=300,
            clock=clock,
        )
        # One verified try per (account, address) while the account is locked
        # (#1001 review): the lockout binds the addresses that failed against
        # *this* account, for the lockout's own horizon rather than the
        # address window's five minutes - or the 15 m and 1 h tiers were dead,
        # and one address's failures against somebody else's name bound the
        # owner on the same NAT.
        self._locked_probe = PersistentRateLimiter(
            session_factory,
            scope="login_lockout_probe",
            limit=1,
            window_seconds=int(LOCKOUT_BACKOFF[-1].total_seconds()),
            clock=clock,
        )
        # Verifications in flight, by key. Process memory is the right place:
        # a slot lasts one hash, and the one worker (R-PLAT-05) sees them all -
        # the one login limit that is not a database bucket (R-RATE-01),
        # because a slot is work in this process, and a row would outlive a
        # crash that never released it.
        self._inflight_accounts: dict[str, int] = {}
        self._inflight_addresses: dict[str, int] = {}

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
        account_key = await self._account_key(username)
        locked_for = await self._lockout_remaining(username, now=now)
        if locked_for > 0 and not await self._locked_probe.peek(
            _pair_key(account_key, address)
        ):
            # The lockout is keyed by the account, and usernames are on every
            # player list: three wrong guesses from anywhere used to lock the
            # owner out, and one wrong guess an hour kept them out (#1001).
            # So it binds the addresses that have failed against this account
            # - the guesser, or the owner mistyping from the same device, who
            # waits the minute it was always meant to cost - and lets a clean
            # address try once, where a correct password gets in and clears it
            # (R-RATE-12). A guesser rotating addresses gets one verified try
            # per address, inside the account window that bounds the total.
            return LoginVerdict(allowed=False, retry_after_seconds=locked_for)
        if not await self._account.peek(account_key):
            return LoginVerdict(allowed=False, retry_after_seconds=900)
        if not await self._address.peek(address):
            return LoginVerdict(allowed=False, retry_after_seconds=300)
        if self._global_limit and not await self._deployment.peek(GLOBAL_LOGIN_KEY):
            # Saturated - but a deployment-wide bucket that refuses everybody
            # is a lever rather than a ceiling: fifty addresses spending their
            # own allowance fill it, and then nobody can sign in however right
            # their password is. It binds the traffic that filled it instead.
            # A caller with failures of their own against either key is part
            # of that traffic and is refused; one with a clean record is not,
            # so a spray is held to a single attempt per address or account
            # while everybody else signs in as usual (R-RATE-12, N-17).
            if await self._address.recent_hits(address) or await self._account.recent_hits(
                account_key
            ):
                return LoginVerdict(allowed=False, retry_after_seconds=300)
        return LoginVerdict(allowed=True)

    def attempt(self, *, username: str, address: str) -> "_Attempt":
        """Hold a verification slot for this account and address (#1001).

        `async with guard.attempt(...) as admitted:` - `admitted` is False
        when either key already has its share of verifications in flight,
        and the caller refuses without hashing. Released on exit, so a slot
        is held for exactly as long as the verification takes.
        """
        return _Attempt(self, username=username, address=address)

    async def note_failure(self, *, username: str, address: str) -> None:
        """Charge every counter, and lengthen this account's backoff."""
        account_key = await self._account_key(username)
        await self._account.check(account_key)
        await self._address.check(address)
        await self._locked_probe.check(_pair_key(account_key, address))
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

def _pair_key(account_key: str, address: str) -> str:
    return f"{account_key}:{address}"


class _Attempt:
    """One verification's hold on the in-flight counters."""

    def __init__(self, guard: LoginGuard, *, username: str, address: str) -> None:
        self._guard = guard
        self._username = username
        self._address = address
        self._account_key: str | None = None
        self.admitted = False

    async def __aenter__(self) -> bool:
        guard = self._guard
        self._account_key = (self._username or "").strip().lower()
        accounts, addresses = guard._inflight_accounts, guard._inflight_addresses
        if (
            accounts.get(self._account_key, 0) >= MAX_INFLIGHT_PER_ACCOUNT
            or addresses.get(self._address, 0) >= MAX_INFLIGHT_PER_ADDRESS
        ):
            return False
        accounts[self._account_key] = accounts.get(self._account_key, 0) + 1
        addresses[self._address] = addresses.get(self._address, 0) + 1
        self.admitted = True
        return True

    async def __aexit__(self, *_exc) -> None:
        if not self.admitted:
            return
        guard = self._guard
        for table, key in (
            (guard._inflight_accounts, self._account_key),
            (guard._inflight_addresses, self._address),
        ):
            left = table.get(key, 0) - 1
            if left > 0:
                table[key] = left
            else:
                table.pop(key, None)


def _locked_until(failures: int, now: datetime) -> datetime | None:
    """How long this many consecutive failures buys, or nothing yet."""
    if failures < LOCKOUT_AFTER_FAILURES:
        return None
    step = min(failures - LOCKOUT_AFTER_FAILURES, len(LOCKOUT_BACKOFF) - 1)
    return now + LOCKOUT_BACKOFF[step]


async def purge_forgotten_lockouts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    budget: SweepBudget | None = None,
) -> SweepReport:
    """Drop lockouts untouched for `LOCKOUT_FORGET_AFTER`, from the hourly sweep.

    The one table an unauthenticated client can add rows to at will: without
    this, growth is set by whoever is guessing, bounded only by the login
    rate limit, and kept for ever (#891). A stale row is already ignored by
    `note_failure`, so removing it changes no decision - it only stops a
    finished attack, and a list of names somebody tried, from being kept.
    """
    cutoff = (now or datetime.now(timezone.utc)) - LOCKOUT_FORGET_AFTER
    return await delete_in_batches(
        session_factory,
        name="auth_login_lockouts",
        candidates=select(AuthLoginLockout.key_hash)
        .where(AuthLoginLockout.updated_at <= cutoff)
        .order_by(AuthLoginLockout.updated_at, AuthLoginLockout.key_hash),
        # The age is asked again: a failure landing between the select and
        # the delete has just made the row current, and it stays.
        delete_for=lambda keys: delete(AuthLoginLockout).where(
            AuthLoginLockout.key_hash.in_(keys),
            AuthLoginLockout.updated_at <= cutoff,
        ),
        budget=budget or sweep_budget_from_env(),
        probe=overdue_probe(
            AuthLoginLockout.updated_at,
            AuthLoginLockout.updated_at <= cutoff,
        ),
        now=cutoff,
    )


async def count_open_lockouts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> int:
    """How many accounts are being held back right now, for the operator view."""
    checked_at = now or datetime.now(timezone.utc)
    async with session_factory() as database:
        return int(
            await database.scalar(
                select(func.count()).where(AuthLoginLockout.locked_until > checked_at)
            )
            or 0
        )
