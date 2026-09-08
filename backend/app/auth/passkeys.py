"""Passkeys: the staff credential a relay cannot carry away (R-AUTH-23).

A TOTP code can be read aloud. That is the whole of the attack N-15 recorded
and declined to close: an attacker on the phone to a moderator gets six digits
and spends them inside their own thirty-second step, and every mitigation
around it - single-use codes, per-action step-up, week-long staff sessions -
narrows the window without shutting it. A WebAuthn assertion is bound to this
deployment's origin by the authenticator itself, so there is nothing to read
out and nothing a lookalike site can obtain.

Two ceremonies, and both are two steps with a challenge in between:

* **Registration** hands the browser a challenge and the parameters an
  authenticator needs, and stores a public key when the signed attestation
  comes back.
* **Assertion** hands out a challenge and verifies the signature over it,
  which is what proves the same authenticator is present now.

The challenge is the whole security of both, so it is held here rather than in
the page: a challenge the client could choose is a signature an attacker could
have collected in advance. It is spent on use and expires quickly
(`CHALLENGE_LIFETIME`), which is the same reasoning as a TOTP step being
recorded when it is used.

`userVerification` is **required**, not preferred. A passkey that only proves
possession is one factor; one that also verifies the person - a fingerprint, a
face, a device PIN - is two in a single gesture, which is what lets a staff
sign-in ask for nothing else (R-AUTH-20). Asking for it and accepting less
would be asking for nothing.

The public key is all this server keeps. There is no shared secret here, which
is the other half of what makes this different from `totp.py`: a database read
gives an attacker a verifier and no way to produce a signature.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.deployment import public_base_url
from app.db.models import (
    User,
    UserPasskey,
    UserSecondFactor,
    WebauthnChallenge,
    generate_uuid,
)

# How long a handed-out challenge is worth anything. Long enough to find a
# fingerprint reader, short enough that a collected one is useless by the time
# it is used somewhere else.
CHALLENGE_LIFETIME = timedelta(minutes=5)

# What each challenge was handed out for. A challenge minted to add a
# credential must not be spendable as a sign-in, which is the one crossing a
# single shared pool would allow.
REGISTER = "register"
AUTHENTICATE = "authenticate"

# The name an authenticator shows in its own prompt and stores beside the key.
RELYING_PARTY_NAME = "Sketchy"


class PasskeyError(Exception):
    """A ceremony that did not check out. Carries what to tell the caller."""


@dataclass(frozen=True)
class RegisteredPasskey:
    """A credential as it is shown to the person who owns it."""

    id: str
    label: str
    created_at: datetime
    last_used_at: datetime | None
    backed_up: bool


def relying_party_id(environ=None) -> str:
    """The domain a credential is bound to, and cannot travel off.

    Derived from `PUBLIC_BASE_URL` rather than from the request, deliberately:
    the request's own Host header is attacker-influenced, and binding a
    credential to whatever a proxy claimed would bind it to nothing. The cost
    is that moving the deployment to another domain invalidates every passkey
    ever registered, which is inherent to WebAuthn rather than to this choice.
    """
    return urlsplit(public_base_url(environ)).hostname or "localhost"


def expected_origin(environ=None) -> str:
    """The exact origin an assertion must name, port and scheme included."""
    return public_base_url(environ)


async def _claim_challenge(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    challenge: str,
    purpose: str,
    user_id: str | None,
) -> bytes:
    """Take the challenge out of the store, or refuse the ceremony.

    One DELETE decides it, and it is committed before anything is verified.
    Both halves of that matter. The condition travels *with* the statement, so
    two requests carrying the same challenge cannot both be told yes - the
    rule a recovery code is claimed under, for the same reason. And the
    commit is separate from the verification that follows, because a deletion
    made inside that transaction is undone when the verification raises: a
    signature that failed would hand the challenge back, and a challenge is
    worth one attempt whether or not the attempt was any good.
    """
    now = datetime.now(timezone.utc)
    conditions = [
        WebauthnChallenge.challenge == challenge,
        WebauthnChallenge.purpose == purpose,
        WebauthnChallenge.expires_at > now,
    ]
    # A registration's challenge belongs to the account that asked for it; a
    # sign-in's belongs to nobody, because nobody has said who they are yet.
    if user_id is None:
        conditions.append(WebauthnChallenge.user_id.is_(None))
    else:
        conditions.append(
            or_(
                WebauthnChallenge.user_id.is_(None),
                WebauthnChallenge.user_id == UUID(user_id),
            )
        )
    async with session_factory() as session:
        async with session.begin():
            claimed = await session.execute(delete(WebauthnChallenge).where(*conditions))
    if not claimed.rowcount:
        raise PasskeyError("That request has expired. Please try again.")
    return base64url_to_bytes(challenge)


async def _store_challenge(
    session: AsyncSession, *, challenge: bytes, purpose: str, user_id: str | None
) -> None:
    now = datetime.now(timezone.utc)
    # Nothing sweeps for these on a timer: each new one clears what this
    # caller left behind, which bounds the table by however many ceremonies
    # are in flight rather than by how many were ever started.
    await session.execute(delete(WebauthnChallenge).where(WebauthnChallenge.expires_at <= now))
    session.add(
        WebauthnChallenge(
            challenge=bytes_to_base64url(challenge),
            purpose=purpose,
            user_id=UUID(user_id) if user_id else None,
            created_at=now,
            expires_at=now + CHALLENGE_LIFETIME,
        )
    )


async def registration_options(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    account: str,
    display_name: str,
    environ=None,
) -> str:
    """What the browser needs to make a credential, as JSON.

    `exclude_credentials` names what this account already holds, so an
    authenticator that is already registered says so instead of quietly making
    a second credential nobody can tell apart from the first.
    """
    async with session_factory() as session:
        async with session.begin():
            held = (
                await session.scalars(
                    select(UserPasskey).where(UserPasskey.user_id == UUID(user_id))
                )
            ).all()
            options = generate_registration_options(
                rp_id=relying_party_id(environ),
                rp_name=RELYING_PARTY_NAME,
                # The account's own id, not its name or email: a user handle
                # travels to the authenticator and is stored there, and this
                # one identifies nobody outside this deployment.
                user_id=UUID(user_id).bytes,
                user_name=account,
                user_display_name=display_name,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    # Discoverable, so signing in needs no username first: the
                    # authenticator knows which account it holds.
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED,
                ),
                exclude_credentials=[
                    PublicKeyCredentialDescriptor(id=base64url_to_bytes(row.credential_id))
                    for row in held
                ],
            )
            await _store_challenge(
                session,
                challenge=options.challenge,
                purpose=REGISTER,
                user_id=user_id,
            )
            return options_to_json(options)


async def register_passkey(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    credential: dict,
    label: str,
    environ=None,
) -> RegisteredPasskey:
    """Check the attestation and keep the public key.

    Nothing is stored until this succeeds, exactly as an abandoned TOTP
    enrolment stores nothing: a ceremony somebody starts and walks away from
    leaves no credential to be confused by later.
    """
    challenge = _client_challenge(credential)
    expected = await _claim_challenge(
        session_factory, challenge=challenge, purpose=REGISTER, user_id=user_id
    )
    async with session_factory() as session:
        async with session.begin():
            try:
                verified = verify_registration_response(
                    credential=credential,
                    expected_challenge=expected,
                    expected_rp_id=relying_party_id(environ),
                    expected_origin=expected_origin(environ),
                    require_user_verification=True,
                )
            except InvalidRegistrationResponse as error:
                raise PasskeyError(
                    "That passkey could not be verified. Please try again."
                ) from error

            credential_id = bytes_to_base64url(verified.credential_id)
            if await session.get(UserPasskey, credential_id) is not None:
                raise PasskeyError("That passkey is already registered.")
            now = datetime.now(timezone.utc)
            row = UserPasskey(
                credential_id=credential_id,
                id=generate_uuid(),
                user_id=UUID(user_id),
                public_key=verified.credential_public_key,
                sign_count=verified.sign_count,
                label=label,
                # Whether the platform keeps a copy. Somebody whose only
                # passkey lives on one device and nowhere else is one lost
                # phone from their recovery codes, and can be told so.
                backed_up=bool(verified.credential_backed_up),
                created_at=now,
            )
            session.add(row)
            return _as_registered(row)


async def authentication_options(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str | None = None,
    environ=None,
) -> str:
    """A challenge to sign, for signing in or for proving it is still you.

    `allow_credentials` is left empty even when the account is known: the
    credential is discoverable, so the authenticator offers what it holds and
    the server learns which one was used from the response. Naming them would
    also tell an unauthenticated caller which credentials an account has.
    """
    async with session_factory() as session:
        async with session.begin():
            options = generate_authentication_options(
                rp_id=relying_party_id(environ),
                user_verification=UserVerificationRequirement.REQUIRED,
            )
            await _store_challenge(
                session,
                challenge=options.challenge,
                purpose=AUTHENTICATE,
                user_id=user_id,
            )
            return options_to_json(options)


@dataclass(frozen=True)
class Assertion:
    """Who signed, and with which credential."""

    user_id: str
    credential_id: str


async def verify_assertion(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    credential: dict,
    expected_user_id: str | None = None,
    environ=None,
) -> Assertion:
    """Check a signature over a challenge this server handed out.

    The signature counter is stored and compared. A counter that goes backwards
    is the one signal WebAuthn gives that a credential has been cloned, and
    authenticators that keep no counter report zero throughout - so a zero is
    accepted and a decrease is not.
    """
    challenge = _client_challenge(credential)
    raw_id = credential.get("rawId") or credential.get("id")
    if not isinstance(raw_id, str):
        raise PasskeyError("That sign-in could not be read.")

    expected = await _claim_challenge(
        session_factory,
        challenge=challenge,
        purpose=AUTHENTICATE,
        user_id=expected_user_id,
    )
    async with session_factory() as session:
        async with session.begin():
            row = await session.get(UserPasskey, raw_id)
            if row is None:
                raise PasskeyError("That passkey is not registered here.")
            if expected_user_id is not None and str(row.user_id) != expected_user_id:
                raise PasskeyError("That passkey belongs to a different account.")
            try:
                verified = verify_authentication_response(
                    credential=credential,
                    expected_challenge=expected,
                    expected_rp_id=relying_party_id(environ),
                    expected_origin=expected_origin(environ),
                    credential_public_key=row.public_key,
                    credential_current_sign_count=row.sign_count,
                    require_user_verification=True,
                )
            except InvalidAuthenticationResponse as error:
                raise PasskeyError(
                    "That passkey could not be verified. Please try again."
                ) from error
            # Compare and swap, not read-then-write. Two assertions verified
            # against the same stored counter each pass their own check and
            # then race to write: the later write wins, and if it carried the
            # *lower* counter the stored one has gone backwards - which is the
            # single thing this column exists to notice. The old value travels
            # in the WHERE, so exactly one of them lands and the other is told
            # to try again.
            #
            # An authenticator that keeps no counter reports zero throughout,
            # and zero swapped for zero still matches: two parallel sign-ins
            # from such a device both succeed, which is right, because a
            # counter that never moves says nothing about cloning either way.
            moved = await session.execute(
                update(UserPasskey)
                .where(
                    UserPasskey.credential_id == row.credential_id,
                    UserPasskey.sign_count == row.sign_count,
                )
                .values(
                    sign_count=verified.new_sign_count,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            if not moved.rowcount:
                raise PasskeyError(
                    "That passkey was used somewhere else at the same moment. "
                    "Please try again."
                )
            return Assertion(user_id=str(row.user_id), credential_id=row.credential_id)


async def list_passkeys(
    session_factory: async_sessionmaker[AsyncSession], *, user_id: str
) -> list[RegisteredPasskey]:
    """Everything this account can sign in with, oldest first."""
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(UserPasskey)
                .where(UserPasskey.user_id == UUID(user_id))
                .order_by(UserPasskey.created_at)
            )
        ).all()
        return [_as_registered(row) for row in rows]


class LastFactorError(PasskeyError):
    """Removing this one would leave the account with no way in."""


async def remove_passkey(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    passkey_id: str,
    keep_one: bool,
) -> bool:
    """Forget one credential, unless it is the last thing standing.

    The rule and the deletion are one transaction on purpose. Counting in one
    and deleting in another is a race an account can lose against itself: two
    requests removing the last two passkeys each see two, each decide the
    other one is still there, and a staff account is left with nothing to
    sign in with. The account row is taken for update first, so the two
    requests queue rather than interleave - on SQLite the write lock does the
    same job.
    """
    owner = UUID(user_id)
    conditions = [UserPasskey.id == UUID(passkey_id), UserPasskey.user_id == owner]
    if keep_one:
        # The rule travels inside the DELETE rather than being read first and
        # trusted afterwards. Both halves of this are needed, and each covers
        # what the other cannot:
        #
        # * The lock below serializes two requests on PostgreSQL, where they
        #   would otherwise delete different rows without ever blocking each
        #   other and both see a count taken before either committed.
        # * The condition here is what protects SQLite, which ignores `FOR
        #   UPDATE` entirely. Its write lock does serialize the statements,
        #   so the second one's count is evaluated after the first has
        #   committed - but only because the count is part of the statement.
        conditions.append(
            or_(
                select(func.count())
                .select_from(UserPasskey)
                .where(UserPasskey.user_id == owner)
                .scalar_subquery()
                > 1,
                exists(
                    select(UserSecondFactor.user_id).where(
                        UserSecondFactor.user_id == owner
                    )
                ),
            )
        )

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                select(User.id).where(User.id == owner).with_for_update()
            )
            removed = await session.execute(delete(UserPasskey).where(*conditions))
            if removed.rowcount:
                return True
            # Nothing went: either there was no such credential, or the rule
            # refused it. Which one decides what the caller is told, and is
            # read inside the same transaction.
            still_there = await session.scalar(
                select(UserPasskey.credential_id).where(
                    UserPasskey.id == UUID(passkey_id),
                    UserPasskey.user_id == owner,
                )
            )
            if still_there is None:
                return False
            raise LastFactorError(
                "This is the only thing this account can sign in with. "
                "Add another passkey or an authenticator app first."
            )


def _client_challenge(credential: dict) -> str:
    """The challenge the browser says it signed, read without trusting it.

    Only used to find the row; what is verified is the challenge that row
    holds, so a client that names somebody else's finds nothing it can use.
    """
    response = credential.get("response")
    if not isinstance(response, dict):
        raise PasskeyError("That response could not be read.")
    client_data = response.get("clientDataJSON")
    if not isinstance(client_data, str):
        raise PasskeyError("That response could not be read.")
    try:
        parsed = json.loads(base64url_to_bytes(client_data))
    except (ValueError, TypeError) as error:
        raise PasskeyError("That response could not be read.") from error
    challenge = parsed.get("challenge")
    if not isinstance(challenge, str):
        raise PasskeyError("That response could not be read.")
    return challenge


def _as_registered(row: UserPasskey) -> RegisteredPasskey:
    return RegisteredPasskey(
        id=str(row.id),
        label=row.label,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        backed_up=row.backed_up,
    )

