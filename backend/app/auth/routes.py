"""REST endpoints for anonymous provisioning, registration, and sign-in."""
from __future__ import annotations

import os
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.account_data import (
    AccountDataError,
    anonymize_account,
    create_data_export,
    decode_export_artifact,
    export_status_payload,
    get_data_export,
    list_data_exports,
    process_data_export,
)
from app.auth.middleware import (
    clear_session_cookie,
    is_secure_request,
    set_session_cookie,
)
from app.auth.sessions import (
    create_session,
    device_label_from_user_agent,
    list_active_sessions,
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
    PASSWORD_RULE_MESSAGE,
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
    confirm_email,
    email_state,
    password_reset_link_is_usable,
    mark_reminder_shown,
    request_email_verification,
    request_password_reset,
    reset_password,
)
from app.api.serializers import user_payload
from app.api.user_settings import UserSettingsSeed, seed_user_settings
from app.auth.rate_limit import PersistentRateLimiter, client_key
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


# GET /api/auth/me runs on every page load, so recording a login timestamp on
# each one would mean a write per visitor per load.
LAST_LOGIN_THROTTLE_SECONDS = 300

# One bucket for the whole deployment, so the daily ceiling is a property of
# the service rather than of whoever happens to be calling. The bucket is a
# database row, so replicas share the number rather than each getting one.
GLOBAL_PROVISION_KEY = "all"



class CredentialsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=MAX_NAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


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
    # Called with each account that lost a friendship or a pending request to
    # a deletion, so their lists stop showing somebody who is gone.
    on_friends_changed: Callable[[str], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/auth")
    # Shared database buckets keep the configured protection honest across
    # deploys, crashes, and multiple application replicas.
    login_limiter = PersistentRateLimiter(
        session_factory,
        scope="login",
        limit=_limit("AUTH_LOGIN_LIMIT", 10),
        window_seconds=300,
    )
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

    def device_label(request: Request) -> str:
        return device_label_from_user_agent(request.headers.get("user-agent"))

    async def issue_cookie(response: Response, request: Request, user_id: str) -> None:
        issued = await create_session(
            session_factory,
            user_id=user_id,
            device_label=device_label(request),
        )
        set_session_cookie(
            response, issued.token, secure=is_secure_request(request)
        )

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

        refreshed = await user_repo.touch_last_login(
            user.id, min_interval_seconds=LAST_LOGIN_THROTTLE_SECONDS
        )
        auth_session = getattr(request.state, "auth_session", None)
        # Rotate rather than merely extending the same credential, limiting
        # how long a copied token remains useful while preserving active guests.
        if auth_session and should_rotate(auth_session):
            rotated = await rotate_session(
                session_factory,
                session_id=auth_session.id,
                user_id=user.id,
                device_label=device_label(request),
            )
            if rotated is not None:
                set_session_cookie(
                    response,
                    rotated.token,
                    secure=is_secure_request(request),
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
            await issue_cookie(response, request, user.id)
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
            raise HTTPException(status_code=400, detail="Invalid color.")

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
            password = validate_password(body.password)
        except PasswordPolicyError as error:
            raise HTTPException(status_code=400, detail=PASSWORD_RULE_MESSAGE) from error

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
        await issue_cookie(response, request, claimed.id)
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
        await throttle(login_limiter, request)
        credentials = await user_repo.get_credentials_by_username(body.username)
        # Hash even when the username does not exist. Skipping it would return
        # noticeably faster and turn response time into a username oracle,
        # which is precisely what the uniform error message avoids.
        password_hash = credentials.password_hash if credentials else DUMMY_HASH
        matched = await verify_password(password_hash, body.password)
        if credentials is None or not matched:
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
        if await is_user_banned(session_factory, credentials.user.id):
            raise HTTPException(status_code=403, detail="This account is suspended.")

        if await password_needs_rehash(credentials.password_hash):
            replacement_hash = await hash_password(body.password)
            await user_repo.replace_password_hash(
                credentials.user.id,
                credentials.password_hash,
                replacement_hash,
            )

        current_user_id = getattr(request.state, "user_id", None)
        current = await user_repo.get_by_id(current_user_id) if current_user_id else None
        if (
            current is not None
            and current.is_anonymous
            and current.id != credentials.user.id
        ):
            try:
                await user_repo.merge_guest_into_account(
                    current.id, credentials.user.id
                )
            except IdentityMergeError as error:
                raise HTTPException(
                    status_code=409,
                    detail="Guest progress could not be linked to this account.",
                ) from error
            if on_identity_merged is not None:
                on_identity_merged(current.id, credentials.user.id)
            await revoke_all_sessions(session_factory, user_id=current.id)

        refreshed = await user_repo.touch_last_login(credentials.user.id)
        await revoke_current(request)
        await issue_cookie(response, request, credentials.user.id)
        return user_payload(refreshed or credentials.user)

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
    async def request_data_export(
        request: Request, background_tasks: BackgroundTasks
    ):
        """Create a durable export job and generate it after responding."""
        user = await require_user(request)
        try:
            job = await create_data_export(session_factory, user_id=user.id)
        except AccountDataError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        background_tasks.add_task(
            process_data_export, session_factory, export_id=job.id
        )
        return export_status_payload(job)

    @router.get("/data-exports")
    async def data_exports(request: Request):
        user = await require_user(request)
        jobs = await list_data_exports(session_factory, user_id=user.id)
        return {"exports": [export_status_payload(job) for job in jobs]}

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
        # The stored document is already JSON; decoding it here and serving the
        # bytes avoids parsing it only to re-serialize the same text.
        try:
            document = decode_export_artifact(job)
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
        return Response(
            content=document,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="sketchy-data-export-{job.id}.json"'
                ),
                "Cache-Control": "private, no-store",
            },
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
        if on_friends_changed is not None:
            for friend_id in result.friends_notified:
                try:
                    await on_friends_changed(friend_id)
                except Exception:
                    logger.exception(
                        "Could not tell %s their friend list changed", friend_id
                    )
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
        try:
            password = validate_password(body.password)
        except PasswordPolicyError as error:
            raise HTTPException(status_code=400, detail=PASSWORD_RULE_MESSAGE) from error
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

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        """Revoke this session. The next /me call provisions a fresh guest."""
        await revoke_current(request)
        clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True}

    return router
