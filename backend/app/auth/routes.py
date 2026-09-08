"""REST endpoints for anonymous provisioning, registration, and sign-in."""
from __future__ import annotations

import os
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.account_data import (
    AccountDataError,
    ExportNotYetAllowed,
    anonymize_account,
    create_data_export,
    export_status_payload,
    get_data_export,
    list_data_exports,
    next_export_allowed_at,
    open_export_artifact,
)
from app.domain_values import DataExportStatus
from app.auth.middleware import (
    clear_session_cookie,
    is_secure_request,
    set_session_cookie,
)
from app.auth.sessions import (
    STAFF_ROLES,
    STEP_UP_WINDOW,
    create_session,
    device_label_from_user_agent,
    list_active_sessions,
    record_step_up,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
    should_rotate,
)
from app.auth.names import (
    MAX_NAME_LENGTH,
    NAME_RULE_MESSAGE,
    NameError_,
    validate_name,
)
from app.auth.password import (
    DUMMY_HASH,
    MAX_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    password_needs_rehash,
    validate_password,
    verify_password,
)
from app.auth.audit import audit_coordinates
from app.auth.bans import is_user_banned
from app.auth.email import EmailAddressError, MAX_EMAIL_LENGTH
from app.auth.mail import mail_is_configured
from app.auth.recovery import (
    EmailAlreadyInUse,
    RecoveryError,
    change_password,
    confirm_email,
    email_state,
    password_reset_identity,
    password_reset_link_is_usable,
    mark_reminder_shown,
    request_email_verification,
    request_password_reset,
    reset_password,
)
from app.api.serializers import user_payload
from app.api.user_settings import UserSettingsSeed, seed_user_settings
from app.auth.rate_limit import PersistentRateLimiter, client_key
from app.auth.login_guard import LoginGuard
from app.auth.passkeys import (
    PasskeyError,
    authentication_options as passkey_authentication_options_json,
    list_passkeys,
    register_passkey,
    registration_options as passkey_registration_options_json,
    remove_passkey,
    verify_assertion,
)
from app.auth.pending_role import take_up_offer
from app.auth.second_factor import (
    SecondFactorOutcome,
    prove_second_factor_owner,
    begin_enrolment,
    confirm_enrolment,
    disable_second_factor,
    replace_recovery_codes,
    second_factor_state,
    verify_second_factor,
)
from app.rooms import normalize_name_color
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    IdentityMergeError,
    UsernameTakenError,
    UserRepository,
)


logger = logging.getLogger(__name__)

def _limit(name: str, default: int) -> int:
    """Read a rate limit from the environment, falling back to the default.

    Configurable because the right ceiling depends on deployment: households
    and offices share one address, and test harnesses need it out of the way.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def staff_second_factor_required() -> bool:
    """Whether a staff role demands an enrolled second factor to sign in.

    On by default, and switchable off for exactly one situation: a deployment
    that has just promoted its first moderators and needs them able to sign in
    long enough to enrol. Leaving it off is leaving R-AUTH-20 unenforced, so
    the readiness surface reports it as a finding rather than as a setting.
    """
    return os.environ.get("STAFF_SECOND_FACTOR_REQUIRED", "1").strip() not in (
        "0",
        "false",
        "no",
    )


# GET /api/auth/me runs on every page load, so recording a login timestamp on
# each one would mean a write per visitor per load.
LAST_LOGIN_THROTTLE_SECONDS = 300


def login_touch_is_due(last_login_at, min_interval_seconds: float) -> bool:
    """Whether recording a login now would move the recorded time."""
    if last_login_at is None or min_interval_seconds <= 0:
        return True
    if last_login_at.tzinfo is None:
        last_login_at = last_login_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_login_at).total_seconds() >= min_interval_seconds

# One bucket for the whole deployment, so the daily ceiling is a property of
# the service rather than of whoever happens to be calling. The bucket is a
# database row, so replicas share the number rather than each getting one.
GLOBAL_PROVISION_KEY = "all"



class CredentialsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=MAX_NAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    # Sent only by a staff sign-in, and only on the second attempt: the first
    # one is what tells the browser a code is wanted (R-AUTH-20). Bounded
    # generously because a recovery code is longer than a TOTP code.
    code: str | None = Field(default=None, max_length=64)


class RegistrationBody(CredentialsBody):
    settings: UserSettingsSeed = Field(default_factory=UserSettingsSeed)
    # Optional, and stays optional. Requiring it would break registration on
    # every deployment with no SMTP configured, which includes the documented
    # zero-configuration default.
    email: str | None = Field(default=None, max_length=MAX_EMAIL_LENGTH)


class EmailBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=MAX_EMAIL_LENGTH)


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(max_length=256)


class ForgotPasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(max_length=MAX_EMAIL_LENGTH)


class ResetPasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(max_length=256)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class DisplayNameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(max_length=MAX_NAME_LENGTH, alias="displayName")


class NameColorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_color: str = Field(max_length=16, alias="nameColor")


class ChangePasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    current_password: str = Field(
        max_length=MAX_PASSWORD_LENGTH, alias="currentPassword"
    )
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class SecondFactorConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Echoed back from the enrolment offer, because nothing was stored: the
    # secret lives in the browser between the two calls and becomes a
    # credential only when this code proves it arrived intact.
    secret: str = Field(max_length=64)
    code: str = Field(max_length=16)
    # Always required: what this writes is later taken as proof the account's
    # owner holds the factor (R-AUTH-20).
    password: str | None = Field(default=None, max_length=MAX_PASSWORD_LENGTH)


class StepUpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=64)


class PasskeyRegistrationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The browser's own object, passed through to the verifier rather than
    # picked apart here: what it contains is WebAuthn's business, and every
    # field of it is checked against a challenge this server chose.
    credential: dict
    # Both proofs, for the reason R-AUTH-20 gives about a second factor: the
    # assertion says an authenticator is present, the password says whose
    # account it is being bound to.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    label: str | None = Field(default=None, max_length=64)


class PasskeyAssertionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: dict


class PasswordProofBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class SecondFactorOwnerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    # Both, and for different reasons: the password says the account's owner
    # is here, the code says they hold the authenticator. Either alone leaves
    # the question this answers open (R-AUTH-20).
    code: str = Field(max_length=16)


class DeleteAccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=MAX_PASSWORD_LENGTH)


def create_auth_router(
    user_repo: UserRepository,
    session_factory,
    *,
    on_account_deleted: Callable[[str], Awaitable[None]] | None = None,
    on_identity_merged: Callable[[str, str], None] | None = None,
    # Called with the account whose display name or colour just changed. The
    # lobby's online list shows both, and it reads them from a cache warmed at
    # the handshake - which is written once, while these can change at any
    # moment and from a request that touches no socket at all.
    on_profile_changed: Callable[[str], None] | None = None,
    # Called with every account that lost a friendship or a pending request
    # to a deletion, so their lists stop showing somebody who is gone. Wired to
    # the friend service's own announcement, so there is one implementation of
    # "tell them their lists moved" rather than one per caller.
    on_friends_changed: Callable[[Iterable[str]], Awaitable[None]] | None = None,
    on_export_requested: Callable[[], None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth")
    # Shared database buckets keep the configured protection honest across
    # deploys, crashes, and multiple application replicas.
    # Account, address and deployment, all counting failures only (#468).
    # The old per-address bucket is one of the three it owns.
    login_guard = LoginGuard(session_factory)
    register_limiter = PersistentRateLimiter(
        session_factory,
        scope="register",
        limit=_limit("AUTH_REGISTER_LIMIT", 10),
        window_seconds=3600,
    )
    lookup_limiter = PersistentRateLimiter(
        session_factory,
        scope="account_lookup",
        limit=_limit("AUTH_LOOKUP_LIMIT", 60),
        window_seconds=60,
    )
    # Provisioning is the one unauthenticated call that writes rows - a
    # `users` row and an `auth_sessions` row - so it is bounded twice. The
    # address key is what a single flooding client meets; the daily ceiling is
    # what still holds behind a reverse proxy, where every caller presents the
    # proxy, and against a botnet, where no address key means anything.
    provision_limiter = PersistentRateLimiter(
        session_factory,
        scope="guest_provision",
        limit=_limit("GUEST_PROVISION_LIMIT", 60),
        window_seconds=3600,
    )
    daily_provision_limiter = PersistentRateLimiter(
        session_factory,
        scope="guest_provision_day",
        limit=_limit("GUEST_PROVISION_DAILY_LIMIT", 5000),
        window_seconds=86400,
    )
    # Guessing six digits is worth throttling on its own account, and an
    # enrolment page reloading in a loop should not mint secrets forever.
    # Tighter than login because nobody legitimately does this often.
    second_factor_limiter = PersistentRateLimiter(
        session_factory,
        scope="second_factor",
        limit=_limit("AUTH_SECOND_FACTOR_LIMIT", 20),
        window_seconds=900,
    )
    # Mailing costs somebody else's inbox, so both of these are tighter than
    # the flows that only cost a database round trip.
    reset_limiter = PersistentRateLimiter(
        session_factory,
        scope="password_reset",
        limit=_limit("AUTH_RESET_LIMIT", 5),
        window_seconds=3600,
    )
    # Looser than requesting a reset: this costs a lookup rather than somebody
    # else's inbox, and one page load with a reload or two must not exhaust it.
    reset_check_limiter = PersistentRateLimiter(
        session_factory,
        scope="password_reset_check",
        limit=_limit("AUTH_RESET_CHECK_LIMIT", 30),
        window_seconds=3600,
    )
    verify_limiter = PersistentRateLimiter(
        session_factory,
        scope="email_verify",
        limit=_limit("AUTH_VERIFY_LIMIT", 10),
        window_seconds=3600,
    )
    # Costs a password verification and a hash rather than somebody's inbox,
    # so it sits between the two - loose enough for a mistyped current
    # password, tight enough that a stolen session cannot grind at one.
    password_change_limiter = PersistentRateLimiter(
        session_factory,
        scope="password_change",
        limit=_limit("AUTH_PASSWORD_CHANGE_LIMIT", 10),
        window_seconds=3600,
    )

    def device_label(request: Request) -> str:
        return device_label_from_user_agent(request.headers.get("user-agent"))

    def _passkey_payload(row) -> dict:
        return {
            "id": row.id,
            "label": row.label,
            "createdAt": row.created_at.isoformat(),
            "lastUsedAt": row.last_used_at.isoformat() if row.last_used_at else None,
            # Whether the platform keeps a copy of it, so somebody with one
            # unsynced passkey can be told what their recovery codes are for.
            "backedUp": row.backed_up,
        }

    async def issue_cookie(
        response: Response,
        request: Request,
        user_id: str,
        role: str | None = None,
    ) -> str:
        """Mint this device's session and set its cookie; return its id.

        The id is returned because a caller that has just proved something
        stronger than a password may want to record it against the session it
        just minted - a passkey assertion, which is the proof a step-up asks
        for (R-AUTH-23).

        `role` decides the lifetime (R-AUTH-03) and every caller here already
        knows it, so it is passed rather than looked up: guest provisioning is
        the busiest write path this server has, and a second read on it buys
        nothing but a connection.
        """
        # From the request, not from a fresh lookup: the middleware has
        # already hashed this caller under the cached secret, and asking the
        # database again on every sign-in and every guest provisioned is a
        # write transaction bought for nothing.
        ip_hash = getattr(request.state, "client_ip_hash", None)
        issued = await create_session(
            session_factory,
            user_id=user_id,
            role=role,
            device_label=device_label(request),
            # The baseline every later use of this session is compared against
            # (R-AUTH-22). A hash, never the address itself.
            ip_hash=ip_hash,
        )
        set_session_cookie(
            response,
            issued.token,
            secure=is_secure_request(request),
            max_age=int(
                (issued.session.expires_at - issued.session.created_at).total_seconds()
            ),
        )
        return issued.session.id

    async def _sign_this_browser_in(response: Response, request: Request, account):
        """Everything that follows a proof, whatever the proof was.

        A password and a passkey answer different questions and arrive at the
        same place: this browser is that account now. What has to happen then
        is the same either way - the guest identity being carried is folded
        into the account and its sessions end (R-ACCT-04), the login is
        stamped, the guest's own session is revoked, and this device is given
        a cookie for the account with the lifetime its role calls for.

        Shared rather than repeated because the half that went missing when a
        second sign-in path was added was the guest merge, and what that costs
        somebody is the game they were in the middle of.
        """
        current_user_id = getattr(request.state, "user_id", None)
        current = await user_repo.get_by_id(current_user_id) if current_user_id else None
        if current is not None and current.is_anonymous and current.id != account.id:
            try:
                await user_repo.merge_guest_into_account(current.id, account.id)
            except IdentityMergeError as error:
                raise HTTPException(
                    status_code=409,
                    detail="Guest progress could not be linked to this account.",
                ) from error
            if on_identity_merged is not None:
                on_identity_merged(current.id, account.id)
            await revoke_all_sessions(session_factory, user_id=current.id)

        refreshed = await user_repo.touch_last_login(account.id)
        await revoke_current(request)
        session_id = await issue_cookie(
            response, request, account.id, role=account.role
        )
        return refreshed or account, session_id

    async def revoke_current(request: Request) -> None:
        session_id = getattr(request.state, "session_id", None)
        user_id = getattr(request.state, "user_id", None)
        if session_id and user_id:
            await revoke_session(
                session_factory, session_id=session_id, user_id=user_id
            )

    async def throttle(limiter: PersistentRateLimiter, request: Request) -> None:
        if not await limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many attempts. Please wait and try again."
            )

    async def _staff_second_factor_gate(user, body, *, address: str):
        """Refuse a staff sign-in that cannot produce its second factor.

        Returns the refusal rather than raising it, so the caller decides
        where in the sequence it lands - which matters, because it has to be
        after the password check and before any session is issued.

        A staff account with no second factor enrolled is refused too, and
        told to enrol. That is the whole force of R-AUTH-20: the alternative,
        letting a moderator work until they get round to enrolling, is a
        requirement that describes an intention rather than a rule. Enrolment
        is done from the account page while still an ordinary player, or by
        signing in during the grace an operator grants with
        `STAFF_SECOND_FACTOR_REQUIRED=0` on a deployment that has just
        promoted somebody.
        """
        if user.role not in STAFF_ROLES or not staff_second_factor_required():
            return None
        state = await second_factor_state(session_factory, user_id=user.id)
        holds_passkey = bool(await list_passkeys(session_factory, user_id=user.id))
        if not state.enrolled:
            if holds_passkey:
                # There is a way in and this is not it. Said as a refusal of
                # the password route rather than of the account, because the
                # account is fine and the browser only has to be pointed at
                # the passkey it already holds (R-AUTH-23).
                return HTTPException(
                    status_code=401,
                    detail="Sign in with your passkey.",
                    headers={"X-Sketchy-Second-Factor": "passkey"},
                )
            return HTTPException(
                status_code=403,
                detail=(
                    "This account needs two-factor authentication before it "
                    "can sign in. Ask an administrator to help you enrol."
                ),
            )
        code = (body.code or "").strip()
        if not code:
            # 401 with a machine-readable reason: the browser has to know to
            # ask for a code rather than to say the password was wrong.
            return HTTPException(
                status_code=401,
                detail="Enter the code from your authenticator app.",
                headers={"X-Sketchy-Second-Factor": "required"},
            )
        outcome = await verify_second_factor(
            session_factory, user_id=user.id, code=code
        )
        if outcome is SecondFactorOutcome.ACCEPTED:
            return None
        if outcome is SecondFactorOutcome.RECOVERY_CODE_SPENT:
            return None
        if outcome is SecondFactorOutcome.LOCKED:
            return HTTPException(
                status_code=429,
                detail="Too many codes were wrong. Please wait and try again.",
            )
        await login_guard.note_failure(username=body.username, address=address)
        return HTTPException(
            status_code=401,
            detail="That code is not right.",
            headers={"X-Sketchy-Second-Factor": "required"},
        )

    async def _prove_password(user, password: str | None) -> None:
        """Refuse unless the caller can produce the account's own password.

        Turning off a second factor, or replacing the codes that bypass it,
        is worth as much to somebody holding a stolen cookie as any staff
        action - so both ask for the one thing a stolen cookie does not carry.
        """
        credentials = (
            await user_repo.get_credentials_by_username(user.username)
            if user.username
            else None
        )
        if (
            credentials is None
            or credentials.user.id != user.id
            or not password
            or not await verify_password(credentials.password_hash, password)
        ):
            raise HTTPException(status_code=401, detail="Password is incorrect.")

    async def refuse_a_registered_name(name: str) -> None:
        """A guest may not play under a name that belongs to an account."""
        owner = await user_repo.get_by_username(name)
        if owner is not None and not owner.is_anonymous:
            raise HTTPException(
                status_code=409, detail="That name belongs to a registered player."
            )

    async def require_user(request: Request):
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return user

    @router.get("/me")
    async def me(request: Request, response: Response):
        """Return the caller's account, or nothing if they do not have one.

        Deliberately creates nothing. This runs on every page load, including
        ones nobody is behind - a crawler, a link preview, an uptime check -
        and provisioning here meant each of those cost a `users` row and an
        `auth_sessions` row. Choosing a name is what creates an account now,
        because that is the first act only a person about to play performs.

        Not write-free, though: a caller who already has an account still has
        their activity recorded and their session rotated when it is due. The
        rule is about creation, which is what an anonymous flood can force.
        """
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None

        if user is None:
            return None

        # The row just read says whether the login touch is due; when it is
        # not, no statement is sent for it at all (#556). The repository
        # repeats the check inside the UPDATE, so two page loads landing
        # together still write once.
        refreshed = None
        if login_touch_is_due(user.last_login_at, LAST_LOGIN_THROTTLE_SECONDS):
            refreshed = await user_repo.touch_last_login(
                user.id, min_interval_seconds=LAST_LOGIN_THROTTLE_SECONDS
            )
        auth_session = getattr(request.state, "auth_session", None)
        # Rotate rather than merely extending the same credential, limiting
        # how long a copied token remains useful while preserving active guests.
        if auth_session and should_rotate(auth_session):
            rotation_ip_hash = getattr(request.state, "client_ip_hash", None)
            rotated = await rotate_session(
                session_factory,
                session_id=auth_session.id,
                user_id=user.id,
                role=user.role,
                device_label=device_label(request),
                ip_hash=rotation_ip_hash,
            )
            if rotated is not None:
                set_session_cookie(
                    response,
                    rotated.token,
                    secure=is_secure_request(request),
                    max_age=int(
                        (
                            rotated.session.expires_at - rotated.session.created_at
                        ).total_seconds()
                    ),
                )
        return user_payload(refreshed or user)

    @router.get("/nickname-available")
    async def nickname_available(request: Request, name: str = ""):
        """Whether a guest may play under this name."""
        await throttle(lookup_limiter, request)
        try:
            candidate = validate_name(name)
        except NameError_:
            return {"available": False, "reason": NAME_RULE_MESSAGE}
        owner = await user_repo.get_by_username(candidate)
        if owner is not None and not owner.is_anonymous:
            return {
                "available": False,
                "reason": "That name belongs to a registered player.",
            }
        return {"available": True, "reason": None}

    @router.post("/display-name")
    async def set_display_name(
        body: DisplayNameBody, request: Request, response: Response
    ):
        """Remember the name a guest chose to play under.

        Kept server-side so the choice survives a cleared localStorage or a
        different device, and so the claim funnel can pre-fill it later.
        """
        await throttle(lookup_limiter, request)
        try:
            name = validate_name(body.display_name)
        except NameError_ as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None
        if user is None:
            # Checked before anything is charged, and before the account
            # exists: the rename path below has always refused a registered
            # player's username, and a first name is no different. Without it
            # the uniqueness rule held everywhere except the one place an
            # account is created.
            await refuse_a_registered_name(name)
            await throttle(provision_limiter, request)
            if not await daily_provision_limiter.check(GLOBAL_PROVISION_KEY):
                logger.warning("guest provisioning is at its daily ceiling")
                # The day refused them, so the hour is still theirs: the
                # ceiling lifts and a caller who bought nothing would
                # otherwise still be blocked by an allowance they never spent.
                await provision_limiter.refund(client_key(request))
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Sketchy is not taking new visitors right now. "
                        "Please try again later."
                    ),
                )
            try:
                user = await user_repo.create_anonymous(display_name=name)
            except Exception:
                # An allowance buys an account; one that bought nothing is
                # given back, the same way a refused room gives back its own.
                await provision_limiter.refund(client_key(request))
                await daily_provision_limiter.refund(GLOBAL_PROVISION_KEY)
                raise
            # A freshly provisioned guest, so the role is known without asking.
            await issue_cookie(response, request, user.id, role=user.role)
            return user_payload(user)
        if not user.is_anonymous:
            # A registered player's name is their username; changing it here
            # would let the two drift apart.
            raise HTTPException(
                status_code=409, detail="Registered players play as their username."
            )

        await refuse_a_registered_name(name)

        updated = await user_repo.update_profile(user.id, display_name=name)
        if on_profile_changed is not None:
            on_profile_changed(user.id)
        return user_payload(updated or user)

    @router.post("/name-color")
    async def set_name_color(body: NameColorBody, request: Request):
        """Remember the color a registered player chose for their name.

        Settings keeps it in localStorage and sends it when joining a room,
        which is enough to color a name in play but leaves it invisible
        everywhere else - a profile, or anyone else's view of this player, has
        no room to read it from. Storing it on the account is what lets a name
        look the same wherever it appears.
        """
        await throttle(lookup_limiter, request)
        color = normalize_name_color(body.name_color)
        if color is None:
            # Shape or readability (#571): the same rule the seat applies.
            raise HTTPException(
                status_code=400,
                detail="Pick a color that reads on both the light and the dark player list.",
            )

        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if user.is_anonymous:
            # Grey italics is the only cue that separates an unclaimed name
            # from a registered one, so a guest color would erase it.
            raise HTTPException(
                status_code=403, detail="Create an account to choose a name color."
            )

        updated = await user_repo.update_profile(user.id, name_color=color)
        if on_profile_changed is not None:
            on_profile_changed(user.id)
        return user_payload(updated or user)

    @router.post("/register")
    async def register(body: RegistrationBody, request: Request, response: Response):
        """Claim the caller's current guest account with a username and password.

        Claiming keeps the same user id, which is what preserves everything the
        player accumulated before signing up.
        """
        await throttle(register_limiter, request)
        try:
            username = validate_name(body.username)
        except NameError_ as error:
            raise HTTPException(status_code=400, detail=NAME_RULE_MESSAGE) from error
        try:
            password = validate_password(
                body.password, username=username, email=body.email
            )
        except PasswordPolicyError as error:
            # The policy's own words, not the generic length sentence: it now
            # refuses for reasons the length sentence does not describe, and
            # "must be 12-128 characters" in answer to a breached password
            # sends somebody straight back with the same password plus a digit.
            raise HTTPException(status_code=400, detail=str(error)) from error

        user_id = getattr(request.state, "user_id", None)
        current = await user_repo.get_by_id(user_id) if user_id else None
        if current is not None and not current.is_anonymous:
            raise HTTPException(
                status_code=409, detail="You are already signed in to an account."
            )

        # Check before creating anything. Creating first and claiming second
        # left an unreachable account behind whenever the name turned out to be
        # taken: committed, cookie-less, and belonging to nobody.
        owner = await user_repo.get_by_username(username)
        if owner is not None:
            raise HTTPException(status_code=409, detail="That username is taken.")

        password_hash = await hash_password(password)
        if current is None:
            # No usable guest session (cookie blocked or expired): create the
            # account outright rather than refusing to let them sign up.
            current = await user_repo.create_anonymous(display_name=username)

        try:
            claimed = await user_repo.claim_account(current.id, username, password_hash)
        except UsernameTakenError as error:
            raise HTTPException(status_code=409, detail="That username is taken.") from error
        except AccountAlreadyClaimedError as error:
            raise HTTPException(
                status_code=409, detail="You are already signed in to an account."
            ) from error

        refreshed = await user_repo.touch_last_login(claimed.id)
        # Claiming keeps the account id but replaces the name it plays under
        # (R-ACCT-05), so a row cached while it was a guest is now wrong in
        # both the name and the grey it was pinned to.
        if on_profile_changed is not None:
            on_profile_changed(claimed.id)
        # The browser's current local preferences become the account's initial
        # cross-device copy exactly once. Later registration retries cannot
        # overwrite a row that already exists.
        await seed_user_settings(
            session_factory, user_id=claimed.id, values=body.settings
        )
        await revoke_current(request)
        await issue_cookie(response, request, claimed.id, role=claimed.role)
        if body.email:
            # Offered, not required, and never fatal: an address that cannot be
            # accepted must not undo an account that has just been claimed.
            request_id, ip_hash = await audit_coordinates(request, session_factory)
            try:
                await request_email_verification(
                    session_factory,
                    user_id=UUID(claimed.id),
                    email=body.email,
                    ip_hash=ip_hash,
                    request_id=request_id,
                )
            except (EmailAddressError, EmailAlreadyInUse, RecoveryError):
                logger.info("Registration email not accepted for %s", claimed.id)
        return user_payload(refreshed or claimed)

    @router.post("/login")
    async def login(body: CredentialsBody, request: Request, response: Response):
        """Sign in to an existing account.

        A guest identity becomes an immutable alias of the account. Historical
        rows keep their original user ids and presentation, while account
        history and statistics resolve across both identities.
        """
        address = client_key(request)
        verdict = await login_guard.check(username=body.username, address=address)
        if not verdict.allowed:
            raise HTTPException(
                status_code=429,
                detail=verdict.message,
                headers={"Retry-After": str(verdict.retry_after_seconds)},
            )
        credentials = await user_repo.get_credentials_by_username(body.username)
        # Hash even when the username does not exist. Skipping it would return
        # noticeably faster and turn response time into a username oracle,
        # which is precisely what the uniform error message avoids.
        password_hash = credentials.password_hash if credentials else DUMMY_HASH
        matched = await verify_password(password_hash, body.password)
        if credentials is None or not matched:
            # Charged here rather than before the check, so signing in
            # correctly costs nothing at all and the ceilings can be low
            # enough to matter (#468). A username that does not exist is
            # charged exactly like one that does: the counters must not be
            # the thing that answers R-AUTH-09's question.
            await login_guard.note_failure(username=body.username, address=address)
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
        if await is_user_banned(session_factory, credentials.user.id):
            raise HTTPException(status_code=403, detail="This account is suspended.")
        # A staff account signs in only if it can also prove its second factor
        # (R-AUTH-20). Checked after the password so a wrong password is never
        # told that this account has one, and before anything is issued so a
        # half-authenticated staff session never exists.
        staff_gate = await _staff_second_factor_gate(
            credentials.user, body, address=address
        )
        if staff_gate is not None:
            raise staff_gate
        await login_guard.note_success(username=body.username)

        if await password_needs_rehash(credentials.password_hash):
            replacement_hash = await hash_password(body.password)
            await user_repo.replace_password_hash(
                credentials.user.id,
                credentials.password_hash,
                replacement_hash,
            )

        account, _ = await _sign_this_browser_in(response, request, credentials.user)
        return user_payload(account)

    @router.get("/sessions")
    async def sessions(request: Request):
        """List the caller's active devices without exposing token hashes."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        current_id = getattr(request.state, "session_id", None)
        records = await list_active_sessions(session_factory, user_id=user_id)
        return {
            "sessions": [
                {
                    "id": record.id,
                    "deviceLabel": record.device_label,
                    "createdAt": record.created_at.isoformat(),
                    "lastUsedAt": record.last_used_at.isoformat(),
                    "expiresAt": record.expires_at.isoformat(),
                    # When silence alone would end it, which for most devices
                    # arrives long before `expiresAt` does (R-AUTH-03).
                    "idleExpiresAt": (
                        record.idle_expires_at.isoformat()
                        if record.idle_expires_at
                        else None
                    ),
                    # Shown so somebody can recognize a session that is not
                    # theirs and revoke it (R-AUTH-22). Deliberately a plain
                    # "used from somewhere new", with no address and no place
                    # name: the server holds a hash and could not say where
                    # even if it should.
                    "anomalyAt": (
                        record.anomaly_at.isoformat() if record.anomaly_at else None
                    ),
                    "current": record.id == current_id,
                }
                for record in records
            ]
        }

    @router.delete("/sessions/{session_id}")
    async def revoke_device(session_id: str, request: Request, response: Response):
        """Revoke one device owned by the caller."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        revoked = await revoke_session(
            session_factory, session_id=session_id, user_id=user_id
        )
        if not revoked:
            raise HTTPException(status_code=404, detail="Active session not found.")
        if session_id == getattr(request.state, "session_id", None):
            clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True}

    @router.post("/logout-all")
    async def logout_all(request: Request, response: Response):
        """Revoke every session for the caller, including this device."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        revoked = await revoke_all_sessions(session_factory, user_id=user_id)
        clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True, "revoked": revoked}

    @router.post("/data-exports", status_code=202)
    async def request_data_export(request: Request):
        """Write a durable export job; the export worker builds it (R-PRIV-03)."""
        user = await require_user(request)
        try:
            job = await create_data_export(session_factory, user_id=user.id)
        except ExportNotYetAllowed as error:
            # Too soon, not wrong: 429 with the date, so the client can say
            # when rather than only that (R-PRIV-12).
            headers = {}
            if error.retry_at is not None:
                headers["Retry-After"] = str(
                    max(0, int((error.retry_at - datetime.now(timezone.utc)).total_seconds()))
                )
            raise HTTPException(
                status_code=429, detail=str(error), headers=headers
            ) from error
        except AccountDataError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        # The row is the queue; this only says "now" rather than "next sweep".
        if on_export_requested is not None:
            on_export_requested()
        return export_status_payload(job)

    @router.get("/data-exports")
    async def data_exports(request: Request):
        user = await require_user(request)
        jobs = await list_data_exports(session_factory, user_id=user.id)
        # The newest non-failed job is what the interval is measured from; the
        # client uses this to say when the next export is allowed instead of
        # offering a button that will be refused.
        counted = next(
            (job for job in jobs if job.status != DataExportStatus.FAILED.value),
            None,
        )
        next_at, _ = next_export_allowed_at(counted, datetime.now(timezone.utc))
        return {
            "exports": [export_status_payload(job) for job in jobs],
            "nextRequestAt": next_at.isoformat() if next_at else None,
        }

    @router.get("/data-exports/{export_id}")
    async def data_export_status(export_id: str, request: Request):
        user = await require_user(request)
        try:
            job = await get_data_export(
                session_factory, export_id=export_id, user_id=user.id
            )
        except AccountDataError as error:
            raise HTTPException(status_code=404, detail="Export not found.") from error
        if job is None:
            raise HTTPException(status_code=404, detail="Export not found.")
        if job.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Export has expired.")
        return export_status_payload(job)

    @router.get("/data-exports/{export_id}/download")
    async def download_data_export(export_id: str, request: Request):
        user = await require_user(request)
        try:
            job = await get_data_export(
                session_factory, export_id=export_id, user_id=user.id
            )
        except AccountDataError as error:
            raise HTTPException(status_code=404, detail="Export not found.") from error
        if job is None:
            raise HTTPException(status_code=404, detail="Export not found.")
        if job.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Export has expired.")
        if job.status != "ready" or job.artifact is None:
            raise HTTPException(status_code=409, detail="Export is not ready.")
        # The stored document is already JSON, already gzip: a client that
        # accepts gzip gets the row's bytes untouched, and one that does not
        # gets them decompressed a chunk at a time. Never parsed, never held
        # whole, and never compressed twice - the response middleware leaves
        # a body that already names its encoding alone (R-PRIV-14).
        try:
            document = open_export_artifact(job)
        except AccountDataError as error:
            # A row flagged ready whose document cannot be read is the server's
            # fault, not the caller's, and the remedy is a fresh export rather
            # than a retry of this one.
            logger.exception(
                "Data export %s is ready but its document is unreadable", job.id
            )
            raise HTTPException(
                status_code=500,
                detail="Export document could not be read. Request a new export.",
            ) from error
        headers = {
            "Content-Disposition": (
                f'attachment; filename="sketchy-data-export-{job.id}.json"'
            ),
            "Cache-Control": "private, no-store",
        }
        if "gzip" in request.headers.get("accept-encoding", "").lower():
            return Response(
                content=document.stored,
                media_type="application/json",
                headers={
                    **headers,
                    "Content-Encoding": "gzip",
                    "Content-Length": str(len(document.stored)),
                    # The middleware adds this on the bodies it encodes; a
                    # body it leaves alone has to say so itself.
                    "Vary": "Accept-Encoding",
                },
            )
        return StreamingResponse(
            document.chunks,
            media_type="application/json",
            headers={**headers, "Content-Length": str(document.size)},
        )

    @router.delete("/account")
    async def delete_account(
        body: DeleteAccountBody, request: Request, response: Response
    ):
        """Anonymize this identity without deleting shared game results."""
        user = await require_user(request)
        if not user.is_anonymous:
            if not body.password:
                raise HTTPException(
                    status_code=400, detail="Enter your password to delete the account."
                )
            credentials = (
                await user_repo.get_credentials_by_username(user.username)
                if user.username
                else None
            )
            if (
                credentials is None
                or credentials.user.id != user.id
                or not await verify_password(credentials.password_hash, body.password)
            ):
                raise HTTPException(status_code=401, detail="Password is incorrect.")
        try:
            result = await anonymize_account(session_factory, user_id=user.id)
        except AccountDataError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        # Their friends lose a row too, and are still connected to hear it.
        # Best effort and after the commit, like every other notification: the
        # deletion is done, and a socket that missed this sees it on the next
        # read.
        # No `try` of its own: the friend service isolates each recipient and
        # logs, so a wrapper here would only be able to hide the one failure
        # it cannot see anyway.
        if on_friends_changed is not None and result.friends_notified:
            await on_friends_changed(result.friends_notified)
        if on_account_deleted is not None:
            try:
                await on_account_deleted(result.user_id)
            except Exception:
                # The database deletion is already committed and must not be
                # presented as failed. Revoked credentials prevent a new
                # connection; this hook only removes an already-live seat.
                logger.exception(
                    "Could not remove deleted account %s from live rooms",
                    result.user_id,
                )
        clear_session_cookie(response, secure=is_secure_request(request))
        return {
            "ok": True,
            "identitiesAnonymized": result.identities_anonymized,
            "sessionsRevoked": result.sessions_revoked,
        }

    @router.get("/email")
    async def read_email(request: Request):
        """What this account knows about its own way back in."""
        user = await require_user(request)
        state = await email_state(session_factory, user_id=UUID(user.id))
        return {
            "address": state.address,
            "verified": state.verified,
            "pendingAddress": state.pending_address,
            "reminderDue": state.reminder_due,
            "deliveryConfigured": mail_is_configured(),
        }

    @router.put("/email")
    async def set_email(body: EmailBody, request: Request):
        """Ask to use an address. It is recorded only once it is proved."""
        user = await require_user(request)
        await throttle(verify_limiter, request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        try:
            address = await request_email_verification(
                session_factory,
                user_id=UUID(user.id),
                email=body.email,
                ip_hash=ip_hash,
                request_id=request_id,
            )
        except EmailAddressError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except EmailAlreadyInUse as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RecoveryError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        return {"ok": True, "pendingAddress": address}

    @router.post("/email/verify")
    async def verify_email(body: TokenBody, request: Request):
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        try:
            address = await confirm_email(
                session_factory,
                token=body.token,
                ip_hash=ip_hash,
                request_id=request_id,
            )
        except EmailAlreadyInUse as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if address is None:
            raise HTTPException(
                status_code=400,
                detail="That confirmation link has expired or already been used.",
            )
        return {"ok": True, "address": address}

    @router.post("/email/reminder-seen")
    async def acknowledge_email_reminder(request: Request):
        """Restart the clock, so the note returns rather than repeats."""
        user = await require_user(request)
        await mark_reminder_shown(session_factory, user_id=UUID(user.id))
        return {"ok": True}

    @router.post("/password/forgot")
    async def forgot_password(body: ForgotPasswordBody, request: Request):
        """Mail a reset link, and say nothing about whether there was one to mail.

        The same answer either way: this response is not a place to find out
        which usernames and addresses are real.
        """
        await throttle(reset_limiter, request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        await request_password_reset(
            session_factory,
            identifier=body.identifier,
            ip_hash=ip_hash,
            request_id=request_id,
        )
        return {
            "ok": True,
            "detail": (
                "If that account exists and has a confirmed email address, "
                "a reset link is on its way."
            ),
        }

    @router.post("/password/reset/check")
    async def check_reset_link(body: TokenBody, request: Request):
        """Is this link still good? Asked when the page opens, so somebody is
        not told the link is dead only after choosing a password.

        Deliberately does not consume it: the person has not set a password
        yet. Throttled like a reset request because it is the same flow being
        walked, even though a 32-byte token makes guessing pointless.
        """
        await throttle(reset_check_limiter, request)
        return {"valid": await password_reset_link_is_usable(
            session_factory, token=body.token
        )}

    @router.post("/password/reset")
    async def perform_password_reset(
        body: ResetPasswordBody, request: Request, response: Response
    ):
        # Read without consuming, so a password refused below leaves the link
        # unspent (R-AUTH-08, R-AUTH-10).
        reset_username, reset_email = await password_reset_identity(
            session_factory, token=body.token
        )
        try:
            password = validate_password(
                body.password, username=reset_username, email=reset_email
            )
        except PasswordPolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        user_id = await reset_password(
            session_factory,
            token=body.token,
            password_hash=await hash_password(password),
            ip_hash=ip_hash,
            request_id=request_id,
        )
        if user_id is None:
            raise HTTPException(
                status_code=400,
                detail="That reset link has expired or already been used.",
            )
        # Every session was revoked, including one held by whoever is standing
        # here. Signing them back in is the point of having reset it.
        clear_session_cookie(response, secure=is_secure_request(request))
        await issue_cookie(response, request, str(user_id))
        return {"ok": True}

    @router.post("/password/change")
    async def change_own_password(
        body: ChangePasswordBody, request: Request, response: Response
    ):
        """Change the password of the account making the request.

        The signed-in counterpart of a reset, for somebody who knows their
        password and simply wants a different one - the reset link exists for
        the case where they do not, and remains the only route for a guest,
        who has no password to change.
        """
        await throttle(password_change_limiter, request)
        user = await require_user(request)
        if user.is_anonymous:
            raise HTTPException(
                status_code=403, detail="Create an account to set a password."
            )
        # The account's own address, read for the screening rule alone
        # (R-AUTH-19): `UserData` deliberately carries no email, and this is
        # a once-in-a-while endpoint rather than a hot path.
        known_email = (
            await email_state(session_factory, user_id=UUID(user.id))
        ).address
        try:
            password = validate_password(
                body.password, username=user.username, email=known_email
            )
        except PasswordPolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        credentials = (
            await user_repo.get_credentials_by_username(user.username)
            if user.username
            else None
        )
        if (
            credentials is None
            or credentials.user.id != user.id
            or not await verify_password(credentials.password_hash, body.current_password)
        ):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        changed = await change_password(
            session_factory,
            user_id=UUID(user.id),
            password_hash=await hash_password(password),
            ip_hash=ip_hash,
            request_id=request_id,
        )
        if not changed:
            raise HTTPException(status_code=409, detail="Could not change the password.")
        # Every session was revoked, this one included. Signing the caller
        # back in is what keeps a password change from also being a logout.
        clear_session_cookie(response, secure=is_secure_request(request))
        await issue_cookie(response, request, user.id, role=user.role)
        return {"ok": True}

    @router.get("/second-factor")
    async def second_factor(request: Request):
        """What this account holds, and whether its role demands one."""
        user = await require_user(request)
        state = await second_factor_state(session_factory, user_id=user.id)
        return {
            "enrolled": state.enrolled,
            "confirmedAt": (
                state.confirmed_at.isoformat() if state.confirmed_at else None
            ),
            "recoveryCodesRemaining": state.recovery_codes_remaining,
            # Whether a staff role could be granted on this factor as it
            # stands, or whether the password still has to be proved for it.
            "passwordProved": state.password_proved,
            "required": user.role in STAFF_ROLES and staff_second_factor_required(),
            "stepUpWindowSeconds": int(STEP_UP_WINDOW.total_seconds()),
        }

    async def _restore_this_device(
        response: Response, request: Request, user_id: str, role: str
    ) -> None:
        """Sign this browser back in, as the role it has just taken up.

        Taking up an offer revokes every session on the account, because a
        staff role must not be reachable from a session issued before a code
        was ever required and because a year-long player cookie must not stay
        year-long on a staff account (R-AUTH-03). Both of those are about the
        *old* credential, and neither is an argument for putting this browser
        through a sign-in: it proved the password and a code from the new
        factor one request ago, which is more than the sign-in it would be
        sent to would ask for.

        So the old session goes and a new one is minted here with the staff
        lifetime. The practical difference is that the recovery codes in this
        response can still be read: they are shown exactly once, and signing
        the browser out from under them would take them off the screen.
        """
        await issue_cookie(response, request, user_id, role=role)

    # --- passkeys (R-AUTH-23) ---------------------------------------------
    #
    # Staff only, and deliberately: two-factor authentication is a staff
    # control (R-AUTH-20), and a passkey is what it is made of now. Whether an
    # ordinary player may hold one - and whether it could replace their
    # password - is an open question rather than a refusal (#684), and the
    # blocker is recovery: email is optional on this deployment, so a
    # passkey-only player who loses their platform account has no route back
    # that this server can offer.

    def _may_hold_a_passkey(user) -> bool:
        """Staff, or somebody a role is waiting on."""
        return user.role in STAFF_ROLES or bool(getattr(user, "pending_role", None))

    async def _require_passkey_holder(request: Request):
        user = await require_user(request)
        if user.is_anonymous or not _may_hold_a_passkey(user):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Passkeys are for moderator and administrator accounts. "
                    "You will be asked to set one up if you are ever offered "
                    "a role."
                ),
            )
        return user

    @router.post("/passkeys/options")
    async def passkey_registration_options(request: Request):
        """What the browser needs to make a credential.

        Throttled with the second factor, which is the same thing being set
        up: a page reloading in a loop should not mint challenges for ever.
        """
        await throttle(second_factor_limiter, request)
        user = await _require_passkey_holder(request)
        return {
            "options": await passkey_registration_options_json(
                session_factory,
                user_id=user.id,
                account=user.username or user.display_name,
                display_name=user.display_name,
            )
        }

    @router.post("/passkeys")
    async def add_passkey(body: PasskeyRegistrationBody, request: Request, response: Response):
        """Keep the public key, and start a role that was waiting on it.

        The password is asked for here and not at every later assertion: it is
        what says this credential is being added by the account's owner rather
        than by somebody holding a stolen cookie, which is the same question
        `password_proved_at` answers for an authenticator app.
        """
        await throttle(second_factor_limiter, request)
        user = await _require_passkey_holder(request)
        await _prove_password(user, body.password)
        try:
            registered = await register_passkey(
                session_factory,
                user_id=user.id,
                credential=body.credential,
                label=(body.label or device_label(request))[:64],
            )
        except PasskeyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        # A passkey answers R-AUTH-20 on its own - registering it proved the
        # password, and a promotion reads the credential itself - so a role
        # waiting on this is now theirs.
        #
        # Deliberately *not* `prove_second_factor_owner`: that vouches for an
        # authenticator app, and this ceremony proves nothing about one. A
        # factor planted with a stolen cookie would otherwise become trusted
        # the moment its victim added a passkey, which is the planted-factor
        # attack R-AUTH-20 exists to refuse, arriving through a side door.
        granted = await take_up_offer(session_factory, user_id=user.id)
        if granted:
            await _restore_this_device(response, request, user.id, granted)
        return {"passkey": _passkey_payload(registered), "roleGranted": granted}

    @router.get("/passkeys")
    async def read_passkeys(request: Request):
        """Everything this account can sign in with."""
        user = await require_user(request)
        if user.is_anonymous or not _may_hold_a_passkey(user):
            return {"passkeys": [], "canHold": False}
        return {
            "passkeys": [
                _passkey_payload(row)
                for row in await list_passkeys(session_factory, user_id=user.id)
            ],
            "canHold": True,
        }

    @router.delete("/passkeys/{passkey_id}")
    async def forget_passkey(
        passkey_id: str, body: PasswordProofBody, request: Request
    ):
        """Remove one credential, unless it is the last thing standing.

        A staff account may not take away its own last way in: the same rule
        that stops one deleting its authenticator app, and for the same
        reason - giving up the role is what removes the requirement, not
        deleting the credential the role depends on.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        await _prove_password(user, body.password)
        held = await list_passkeys(session_factory, user_id=user.id)
        factor = await second_factor_state(session_factory, user_id=user.id)
        last_one = len(held) <= 1 and not factor.enrolled
        if user.role in STAFF_ROLES and staff_second_factor_required() and last_one:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This is the only thing this account can sign in with. Add "
                    "another passkey or an authenticator app first."
                ),
            )
        if not await remove_passkey(
            session_factory, user_id=user.id, passkey_id=passkey_id
        ):
            raise HTTPException(status_code=404, detail="No such passkey.")
        return {"ok": True}

    @router.post("/passkeys/challenge")
    async def passkey_challenge(request: Request):
        """A challenge to sign. Answered to anybody, on purpose.

        Signing in with a passkey happens before anybody has said who they
        are, and the challenge says nothing about who holds what: it is a
        random number this server will remember for five minutes.
        """
        await throttle(second_factor_limiter, request)
        return {
            "options": await passkey_authentication_options_json(session_factory)
        }

    @router.post("/passkeys/verify")
    async def verify_passkey(
        body: PasskeyAssertionBody, request: Request, response: Response
    ):
        """Sign in with a passkey, or prove it is still you.

        One endpoint because it is one act: an assertion over a challenge this
        server chose, verified against a stored public key. What it is *for*
        is decided by whether the caller already holds a session on the
        account that signed - stepping up if so, signing in if not.
        """
        await throttle(second_factor_limiter, request)
        try:
            assertion = await verify_assertion(session_factory, credential=body.credential)
        except PasskeyError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

        account = await user_repo.get_by_id(assertion.user_id)
        if account is None:
            raise HTTPException(status_code=401, detail="That passkey is not registered here.")
        if await is_user_banned(session_factory, account.id):
            raise HTTPException(status_code=403, detail="This account is suspended.")

        if getattr(request.state, "user_id", None) == account.id:
            session_id = getattr(request.state, "session_id", None)
            if session_id and await record_step_up(
                session_factory, session_id=session_id, user_id=account.id
            ):
                return {"ok": True, "user": user_payload(account), "steppedUp": True}
            raise HTTPException(
                status_code=409,
                detail="This session has been replaced. Reload and try again.",
            )

        signed_in, session_id = await _sign_this_browser_in(response, request, account)
        # The assertion *is* the proof a step-up asks for, and it happened one
        # request ago. A code is not treated this way because a code can be
        # relayed and this cannot: that difference is the whole of R-AUTH-23.
        await record_step_up(
            session_factory, session_id=session_id, user_id=account.id
        )
        return {"ok": True, "user": user_payload(signed_in), "steppedUp": True}

    @router.post("/second-factor/enrol")
    async def start_second_factor_enrolment(request: Request):
        """Offer a secret. Nothing is stored until a code proves it arrived.

        Throttled, because each call is a fresh secret and an enrolment page
        left reloading would otherwise be an unbounded source of them.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        if user.is_anonymous:
            raise HTTPException(
                status_code=403,
                detail="Create an account before setting up two-factor authentication.",
            )
        offer = begin_enrolment(account=user.username or user.display_name)
        return {"secret": offer.secret, "uri": offer.uri}

    @router.post("/second-factor/confirm")
    async def confirm_second_factor(
        body: SecondFactorConfirmBody, request: Request, response: Response
    ):
        """Prove the secret arrived, and receive the recovery codes.

        The codes are in this response and in no other: they exist as hashes
        from here on, exactly as session tokens do (R-AUTH-02), so a second
        request for the same set is not something this server can answer.

        Setting one up asks for nothing but the code. A password here was a
        lot to demand of somebody doing something optional, and the reason it
        was demanded was never really about this moment - it was about
        promotion, which used to check that a second factor *existed* rather
        than whose it was. That question moved to where it belongs
        (R-AUTH-20): a password given here is recorded as proof, and only the
        role gate insists on having it.

        Replacing one still proves the password, because that destroys a
        credential the way removing it does.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        already = await second_factor_state(session_factory, user_id=user.id)
        if already.enrolled:
            await _prove_password(user, body.password)
        elif body.password:
            # Offered rather than demanded: somebody who gives it here is
            # spared the separate step before a role can be granted.
            await _prove_password(user, body.password)
        codes = await confirm_enrolment(
            session_factory,
            user_id=user.id,
            secret=body.secret,
            code=body.code,
            password_proved=bool(body.password),
        )
        if codes is None:
            raise HTTPException(
                status_code=400,
                detail="That code is not right. Check your authenticator app.",
            )
        # And if a role was waiting on exactly this, it is now theirs. The
        # order matters: the factor is written first, so a failure here leaves
        # an account with a second factor and an offer still standing rather
        # than a staff role with nothing to sign in with.
        granted = (
            await take_up_offer(session_factory, user_id=user.id)
            if body.password
            else None
        )
        if granted:
            await _restore_this_device(response, request, user.id, granted)
        return {"ok": True, "recoveryCodes": codes, "roleGranted": granted}

    @router.post("/second-factor/confirm-owner")
    async def confirm_second_factor_owner(
        body: SecondFactorOwnerBody, request: Request, response: Response
    ):
        """Record that this factor is the account owner's (R-AUTH-20).

        Setting one up does not ask for a password, so a factor may be in
        place without anybody having proved it belongs to whoever owns the
        account. A staff role needs that proof, and this is how it is given -
        without tearing the factor down and scanning it again.

        Both proofs, because the two say different things. A password says
        the account's owner is the one asking; a code says they hold the
        authenticator that is enrolled. A password alone would be satisfied
        by the owner of an account somebody else planted a factor on - the
        exact case this gate exists to catch - because the owner would be
        vouching for an authenticator they have never seen.

        The password is checked first so that a wrong one costs no code
        attempt: the failures counted against a factor lock it, and an
        attacker holding only a session should not be able to lock the owner
        out of proving their own.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        await _prove_password(user, body.password)
        outcome = await verify_second_factor(
            session_factory, user_id=user.id, code=body.code
        )
        if outcome is SecondFactorOutcome.NOT_ENROLLED:
            raise HTTPException(
                status_code=409, detail="Two-factor authentication is not set up."
            )
        if outcome is SecondFactorOutcome.LOCKED:
            raise HTTPException(
                status_code=429,
                detail="Too many codes were wrong. Please wait and try again.",
            )
        if outcome is SecondFactorOutcome.REJECTED:
            # A code just spent - by the enrolment a moment ago, most likely -
            # lands here too, so the way out is said rather than left to be
            # guessed at.
            raise HTTPException(
                status_code=401,
                detail="That code is not right. Wait for the next one and try again.",
            )
        if not await prove_second_factor_owner(session_factory, user_id=user.id):
            raise HTTPException(
                status_code=409, detail="Two-factor authentication is not set up."
            )
        # The same thing enrolment does, for a factor that was set up without a
        # password and has only now been vouched for.
        granted = await take_up_offer(session_factory, user_id=user.id)
        if granted:
            await _restore_this_device(response, request, user.id, granted)
        return {"ok": True, "roleGranted": granted}

    @router.post("/second-factor/recovery-codes")
    async def regenerate_recovery_codes(body: PasswordProofBody, request: Request):
        """Replace the set, proving the password first."""
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        await _prove_password(user, body.password)
        state = await second_factor_state(session_factory, user_id=user.id)
        if not state.enrolled:
            raise HTTPException(
                status_code=409, detail="Two-factor authentication is not set up."
            )
        return {"recoveryCodes": await replace_recovery_codes(
            session_factory, user_id=user.id
        )}

    @router.delete("/second-factor")
    async def remove_second_factor(body: PasswordProofBody, request: Request):
        """Turn it off, unless the account's role is the reason it is on.

        Throttled like every other password proof on this router. It was the
        one that was not, which made it the cheapest place for somebody
        holding a stolen cookie to guess the password that would let them
        take the second factor off an account.

        A moderator cannot remove their own second factor: it is the condition
        of the role, and letting them drop it would leave R-AUTH-20 enforced
        only against people who had not thought to. Giving up the role is what
        removes the requirement, and only an administrator can do that.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        await _prove_password(user, body.password)
        if user.role in STAFF_ROLES and staff_second_factor_required():
            raise HTTPException(
                status_code=409,
                detail=(
                    "Two-factor authentication is required for this account's role."
                ),
            )
        removed = await disable_second_factor(session_factory, user_id=user.id)
        if not removed:
            raise HTTPException(
                status_code=409, detail="Two-factor authentication is not set up."
            )
        return {"ok": True}

    @router.post("/step-up")
    async def step_up(body: StepUpBody, request: Request):
        """Prove the second factor again, for one short window (R-AUTH-21).

        The proof is recorded against this session rather than this request,
        so a moderator working through a queue is asked once rather than per
        action - and revoking the device revokes the proof with it.
        """
        await throttle(second_factor_limiter, request)
        user = await require_user(request)
        session_id = getattr(request.state, "session_id", None)
        if not session_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        outcome = await verify_second_factor(
            session_factory, user_id=user.id, code=body.code
        )
        if outcome is SecondFactorOutcome.NOT_ENROLLED:
            raise HTTPException(
                status_code=409, detail="Two-factor authentication is not set up."
            )
        if outcome is SecondFactorOutcome.LOCKED:
            raise HTTPException(
                status_code=429,
                detail="Too many codes were wrong. Please wait and try again.",
            )
        if outcome is SecondFactorOutcome.REJECTED:
            raise HTTPException(status_code=401, detail="That code is not right.")
        recorded = await record_step_up(
            session_factory, session_id=session_id, user_id=user.id
        )
        if not recorded:
            # The code was right and there was nowhere to put it: the row this
            # request resolved through is revoked or expired, which a caller
            # inside a rotation's grace window is holding by definition. Saying
            # "ok" there would send them straight back into the action that
            # refused them, to be refused again with nothing changed.
            raise HTTPException(
                status_code=409,
                detail="This session has been replaced. Reload and try again.",
            )
        return {
            "ok": True,
            "expiresInSeconds": int(STEP_UP_WINDOW.total_seconds()),
        }

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        """Revoke this session. The next /me call provisions a fresh guest."""
        await revoke_current(request)
        clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True}

    return router
