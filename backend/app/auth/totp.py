"""RFC 6238 time-based one-time passwords, and the codes that replace them.

Written out rather than pulled in. The algorithm is an HMAC of a counter,
truncated - about thirty lines, all of it in the standard library - and the
alternative was a dependency on this server's authentication path, which is
the last place to take one for thirty lines. The backend's whole dependency
set is argon2, the SQLAlchemy stack and the web server, and this keeps it that
way.

TOTP is not phishing-resistant, and choosing it was a trade rather than an
oversight. A relay that fools a moderator into reading a code aloud can spend
it inside its thirty-second step, which WebAuthn's origin-bound assertion
would have prevented. What it costs to close that hole is three new
dependencies (a WebAuthn library, a cryptography backend, a CBOR decoder), a
registration and an assertion ceremony on both sides, and a browser API that
is not available on every device staff might use. R-AUTH-20 records the
decision and N-11 records what it deliberately does not solve; the mitigations
that remain are that a code is single-use even inside its own step, that
step-up is required per destructive action rather than once per session
(R-AUTH-21), and that staff sessions last a week rather than a year.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote


# Thirty seconds, six digits, SHA-1: the parameters every authenticator app
# assumes when a provisioning URI does not say otherwise. Naming them anyway,
# because a URI that omits them relies on the app's default rather than on an
# agreement. SHA-1 here is HMAC-SHA-1, whose security does not rest on the
# collision resistance SHA-1 lost.
STEP_SECONDS = 30
DIGITS = 6
# One step either side, so a phone whose clock is half a minute out still
# works. Wider than this starts to matter: every extra step is another code
# valid at any moment.
ALLOWED_DRIFT_STEPS = 1
# 160 bits, the RFC 4226 recommendation, and a whole number of base32
# characters so the string a person may have to type has no padding in it.
SECRET_BYTES = 20

RECOVERY_CODE_COUNT = 10
# Ten characters of Crockford-ish base32 is about 50 bits - far past guessing,
# and short enough to write on paper. Ambiguous characters are left out
# because these get copied by hand.
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
RECOVERY_CODE_LENGTH = 10

# After this many wrong codes in a row the second factor stops answering for
# a while. Six digits is a million possibilities, but a million is not many
# for a machine, and the throttle in front of login does not cover a caller
# who already has the password and is grinding the second factor.
MAX_SECOND_FACTOR_FAILURES = 5


def generate_secret() -> str:
    """A fresh base32 shared secret, without padding."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, *, account: str, issuer: str = "Sketchy") -> str:
    """The `otpauth://` URI an authenticator app scans or accepts pasted.

    Carries the parameters explicitly rather than relying on app defaults, and
    names the issuer twice - in the label and as a parameter - because older
    apps read one and newer ones read the other.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _decode_secret(secret: str) -> bytes:
    padded = secret + "=" * (-len(secret) % 8)
    return base64.b32decode(padded, casefold=True)


def code_at(secret: str, step: int) -> str:
    """The code for one counter value: HMAC, dynamic truncation, modulo."""
    digest = hmac.new(
        _decode_secret(secret), struct.pack(">Q", step), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**DIGITS)).zfill(DIGITS)


def current_step(timestamp: float) -> int:
    """Which thirty-second interval a moment falls in."""
    return int(timestamp) // STEP_SECONDS


def matching_step(secret: str, code: str, *, timestamp: float) -> int | None:
    """The interval this code belongs to, or None.

    Returns the step rather than a boolean so the caller can refuse a code
    whose step has already been spent. Every candidate is compared in constant
    time, and the loop does not stop early on a match, so neither the answer
    nor the time taken says which step it was.
    """
    cleaned = "".join(character for character in code if character.isdigit())
    if len(cleaned) != DIGITS:
        return None
    now_step = current_step(timestamp)
    found: int | None = None
    for offset in range(-ALLOWED_DRIFT_STEPS, ALLOWED_DRIFT_STEPS + 1):
        step = now_step + offset
        if step < 0:
            continue
        if hmac.compare_digest(code_at(secret, step), cleaned) and found is None:
            found = step
    return found


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Single-use codes, shown once and stored only as hashes."""
    return [
        "".join(
            secrets.choice(RECOVERY_CODE_ALPHABET)
            for _ in range(RECOVERY_CODE_LENGTH)
        )
        for _ in range(count)
    ]


def normalize_recovery_code(code: str) -> str:
    """Fold away how somebody typed it: case, spaces, and separators."""
    return "".join(
        character
        for character in code.upper()
        if character in RECOVERY_CODE_ALPHABET
    )


def hash_recovery_code(code: str) -> str:
    """One-way digest, for the same reason `hash_session_token` is one."""
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
