"""REST endpoints for anonymous provisioning, registration, and sign-in."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

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
from app.api.serializers import user_payload
from app.auth.rate_limit import RateLimiter, client_key
from app.rooms import normalize_name_color
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    IdentityMergeError,
    UsernameTakenError,
    UserRepository,
)

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


# Generous enough that a person fumbling their password is never locked out,
# tight enough that online guessing and username scraping are impractical.
login_limiter = RateLimiter(limit=_limit("AUTH_LOGIN_LIMIT", 10), window_seconds=300)
register_limiter = RateLimiter(
    limit=_limit("AUTH_REGISTER_LIMIT", 10), window_seconds=3600
)
lookup_limiter = RateLimiter(limit=_limit("AUTH_LOOKUP_LIMIT", 60), window_seconds=60)

# GET /api/auth/me runs on every page load, so recording a login timestamp on
# each one would mean a write per visitor per load.
LAST_LOGIN_THROTTLE_SECONDS = 300



class CredentialsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=MAX_NAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class DisplayNameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(max_length=MAX_NAME_LENGTH, alias="displayName")


class NameColorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_color: str = Field(max_length=16, alias="nameColor")


def create_auth_router(user_repo: UserRepository, session_factory) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

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

    def throttle(limiter: RateLimiter, request: Request) -> None:
        if not limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many attempts. Please wait and try again."
            )

    @router.get("/me")
    async def me(request: Request, response: Response):
        """Return the caller's account, creating a guest on first visit.

        The only endpoint that provisions. Everything else merely reads the
        cookie, so background traffic like the lobby room-list poll can never
        create user rows.
        """
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None

        if user is None:
            user = await user_repo.create_anonymous(display_name="")
            await issue_cookie(response, request, user.id)
            return user_payload(user)

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
        throttle(lookup_limiter, request)
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
        throttle(lookup_limiter, request)
        try:
            name = validate_name(body.display_name)
        except NameError_ as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None
        if user is None:
            user = await user_repo.create_anonymous(display_name=name)
            await issue_cookie(response, request, user.id)
            return user_payload(user)
        if not user.is_anonymous:
            # A registered player's name is their username; changing it here
            # would let the two drift apart.
            raise HTTPException(
                status_code=409, detail="Registered players play as their username."
            )

        owner = await user_repo.get_by_username(name)
        if owner is not None and not owner.is_anonymous:
            raise HTTPException(
                status_code=409, detail="That name belongs to a registered player."
            )

        updated = await user_repo.update_profile(user.id, display_name=name)
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
        throttle(lookup_limiter, request)
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
        return user_payload(updated or user)

    @router.post("/register")
    async def register(body: CredentialsBody, request: Request, response: Response):
        """Claim the caller's current guest account with a username and password.

        Claiming keeps the same user id, which is what preserves everything the
        player accumulated before signing up.
        """
        throttle(register_limiter, request)
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
        await revoke_current(request)
        await issue_cookie(response, request, claimed.id)
        return user_payload(refreshed or claimed)

    @router.post("/login")
    async def login(body: CredentialsBody, request: Request, response: Response):
        """Sign in to an existing account.

        A guest identity becomes an immutable alias of the account. Historical
        rows keep their original user ids and presentation, while account
        history and statistics resolve across both identities.
        """
        throttle(login_limiter, request)
        credentials = await user_repo.get_credentials_by_username(body.username)
        # Hash even when the username does not exist. Skipping it would return
        # noticeably faster and turn response time into a username oracle,
        # which is precisely what the uniform error message avoids.
        password_hash = credentials.password_hash if credentials else DUMMY_HASH
        matched = await verify_password(password_hash, body.password)
        if credentials is None or not matched:
            raise HTTPException(status_code=401, detail="Incorrect username or password.")

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

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        """Revoke this session. The next /me call provisions a fresh guest."""
        await revoke_current(request)
        clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True}

    return router
