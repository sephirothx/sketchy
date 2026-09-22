"""Argon2id password hashing, kept off the event loop on a capped pool of its own."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError

from app.api.errors import Refusal
from app.auth.breached_passwords import screening_failure
from app.refusals import ErrorCode

# Twelve rather than eight (#468). Eight characters of anything a person
# actually chooses is inside the reach of an offline guess against a stolen
# hash, however good the hashing is - Argon2id raises the cost per guess, and
# a short password lowers the number of guesses needed by more. Twelve is the
# point at which the length rule, rather than the list beside it, is doing the
# work: it removes essentially every entry in a published breach corpus on its
# own (R-AUTH-19).
MIN_PASSWORD_LENGTH = 12
# Argon2 itself has no length limit, but an unbounded password is a cheap way to
# make the server do arbitrary work per request.
MAX_PASSWORD_LENGTH = 128

# OWASP's current Argon2id baseline (19 MiB, t=2, p=1) rather than the library
# defaults, which ask for 64 MiB. This process also runs every live drawing
# stroke for every room, so the memory and latency of a login matter here in a
# way they would not in a request-per-process deployment.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# How many hashes may run at once (#975). Each is ~15 ms of CPU and 19 MiB,
# and they used to run in anyio's shared 40-thread pool with nothing counting
# them: login only *peeks* its limiters before verifying, so a burst reaches
# argon2 all at once. Measured, 200 concurrent verifies there held the event
# loop - every room's strokes and timers - at a p99 lag of ~30 ms and a worst
# of ~70 ms, and peaked ~600 MiB above idle; capped at 4 the same burst left
# the loop at 0.2 ms and took ~58 MiB. Past the
# cap a login waits in this pool's queue, which costs the loop nothing, and
# static files no longer queue behind logins in the shared pool. One core is
# left to the loop by default, since argon2 releases the GIL and keeps a core
# busy per worker.
#
# The cores this process may run on (`process_cpu_count` honours CPU
# affinity). A container quota is not visible here: a 1-vCPU container on a
# large host should set `PASSWORD_HASH_WORKERS=1`.
PASSWORD_HASH_WORKERS_DEFAULT = max(1, min(4, (os.process_cpu_count() or 2) - 1))
# How many hashes may be waiting or running at once before the next is refused
# (#975 review). Login charges a failure only after verifying, so a burst of
# unknown usernames passes its limiters whole; queued without a bound, every
# real login behind it waited N x ~4 ms. Past this depth - about a quarter of
# a second of work at four workers - the caller is told to retry instead.
QUEUED_PER_WORKER = 16
RETRY_AFTER_SECONDS = 1
_executor: ThreadPoolExecutor | None = None
_workers = 0
_outstanding = 0
#: Held only on the path where a closed loop leaves the release to the worker
#: thread; the loop's own releases stay single-threaded.
_release_lock = threading.Lock()


class PasswordHashingBusy(Refusal):
    """More hashing is waiting than the pool gets through in a moment.

    A server-state refusal rather than `too_fast`, which would tell a player
    who did nothing wrong to slow down (#975 review).
    """

    def __init__(self) -> None:
        super().__init__(
            503,
            ErrorCode.SERVER_BUSY,
            "The server is busy signing people in. Try again in a moment.",
            retry_after_ms=RETRY_AFTER_SECONDS * 1000,
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )


def password_hash_workers() -> int:
    """The configured cap, validated; `PASSWORD_HASH_WORKERS` overrides it."""
    raw = os.environ.get("PASSWORD_HASH_WORKERS", "").strip()
    if not raw:
        return PASSWORD_HASH_WORKERS_DEFAULT
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError("PASSWORD_HASH_WORKERS must be an integer") from error
    if not 1 <= value <= 32:
        raise ValueError("PASSWORD_HASH_WORKERS must be between 1 and 32")
    return value


def _pool() -> ThreadPoolExecutor:
    global _executor, _workers
    if _executor is None:
        _workers = password_hash_workers()
        _executor = ThreadPoolExecutor(max_workers=_workers, thread_name_prefix="argon2")
    return _executor


def max_queued() -> int:
    """Hashes that may be waiting or running before the next is refused."""
    _pool()
    return _workers * QUEUED_PER_WORKER


async def _off_loop(function, *args):
    """Run one hashing call on the capped pool, or refuse if it is backed up.

    The count is only ever written on the event loop - the worker thread posts
    its release back - so it needs no lock.
    """
    global _outstanding
    pool = _pool()
    if _outstanding >= max_queued():
        raise PasswordHashingBusy()
    loop = asyncio.get_running_loop()
    # Submitted first: a `submit` that raises must not leave a slot taken for
    # the life of the process (#975 third review).
    job = pool.submit(function, *args)
    _outstanding += 1
    # Counted out when the job itself ends, not when the caller stops waiting:
    # a cancelled caller leaves queued work behind, and releasing its slot
    # there would let the queue grow past the cap unseen (#975 review). The
    # callback runs on the worker thread, so the count is put back on the loop
    # rather than written from there.
    job.add_done_callback(lambda _job: _release_on(loop))
    return await asyncio.wrap_future(job)


def _release_on(loop: asyncio.AbstractEventLoop) -> None:
    """Put one slot back, from whichever thread the job ended on.

    Normally the loop does it, so the count stays single-threaded. A loop that
    has already closed - a process shutting down, or a test whose loop ended
    while a hash was still running - refuses the callback, and a slot dropped
    there is one the process never gets back: the refusal floor creeps down
    until everything is answered "busy" (#975 fourth review). So that case is
    counted here instead, under the lock the other threads take.
    """
    try:
        loop.call_soon_threadsafe(_release)
    except RuntimeError:
        with _release_lock:
            _release()


def _release() -> None:
    global _outstanding
    _outstanding -= 1


# Verified against when no account matches the given username, so that path
# costs the same as a real password check and cannot be told apart by timing.
DUMMY_HASH = _hasher.hash("no-such-account")


PASSWORD_RULE_MESSAGE = (
    f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."
)


class PasswordPolicyError(ValueError):
    """A password refused by policy before it is ever hashed.

    Which rule refused it is the whole value of the refusal: somebody who is
    only told "no" comes back with a password one character different. So it
    carries a `reason` a client can write its own sentence from, and `detail`
    for the one reason whose sentence needs a number. The message stays for
    the log (R-I18N-01).
    """

    def __init__(
        self, message: str, *, reason: str, detail: int | None = None
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.detail = detail


def validate_password(
    password: object,
    *,
    username: str | None = None,
    email: str | None = None,
) -> str:
    """Return the password if it satisfies the policy, else raise.

    Length first, then screening (#468). The order matters for what people are
    told: a nine-character password is short, and saying instead that it is a
    common one - which it very likely also is - explains the wrong thing.

    The identity is passed in wherever the caller has it, because a password
    built from the name it protects is the one weak password a list can never
    hold. It is optional rather than required: a reset knows the account, and
    a registration knows the name being claimed, but neither is worth making a
    caller invent when it does not have one (R-AUTH-19).
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("Password must be text", reason="not_text")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            reason="too_short",
            detail=MIN_PASSWORD_LENGTH,
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters",
            reason="too_long",
            detail=MAX_PASSWORD_LENGTH,
        )
    refusal = screening_failure(password, username=username, email=email)
    if refusal is not None:
        raise PasswordPolicyError(
            refusal.sentence, reason=refusal.reason, detail=refusal.detail
        )
    return password


async def hash_password(password: str) -> str:
    """Hash a password without blocking the event loop."""
    return await _off_loop(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against its hash without blocking the event loop."""
    if not password_hash or not isinstance(password, str):
        return False

    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await _off_loop(_verify)


async def password_needs_rehash(password_hash: str) -> bool:
    """Whether a valid encoded hash predates the current Argon2 parameters."""
    if not password_hash:
        return False

    # Inline, not on the pool: it only parses the parameters out of the
    # encoded hash, microseconds, and queued behind the burst a successful
    # login would wait through the backlog twice (#975 review).
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return False
