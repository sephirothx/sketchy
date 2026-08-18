"""REST endpoints for anonymous provisioning, registration, and sign-in."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth.jwt import COOKIE_NAME, create_token, get_or_create_secret, should_refresh
from app.auth.middleware import (
    clear_session_cookie,
    is_secure_request,
    set_session_cookie,
)
from app.auth.names import MAX_NAME_LENGTH, NameError_, validate_name
from app.auth.password import (
    DUMMY_HASH,
    MAX_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)
from app.auth.rate_limit import RateLimiter, client_key
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    UserData,
    UsernameTakenError,
    UserRepository,
)

# Generous enough that a person fumbling their password is never locked out,
# tight enough that online guessing and username scraping are impractical.
login_limiter = RateLimiter(limit=10, window_seconds=300)
register_limiter = RateLimiter(limit=5, window_seconds=3600)
lookup_limiter = RateLimiter(limit=60, window_seconds=60)

# GET /api/auth/me runs on every page load, so recording a login timestamp on
# each one would mean a write per visitor per load.
LAST_LOGIN_THROTTLE_SECONDS = 300



class CredentialsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=MAX_NAME_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


def user_payload(user: UserData) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "nameColor": user.name_color,
        "isAnonymous": user.is_anonymous,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def create_auth_router(user_repo: UserRepository, session_factory) -> APIRouter:
    router = APIRouter(prefix="/api/auth")

    async def issue_cookie(response: Response, request: Request, user_id: str) -> None:
        secret = await get_or_create_secret(session_factory)
        set_session_cookie(
            response, create_token(user_id, secret), secure=is_secure_request(request)
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
        token = getattr(request.state, "session_token", "")
        secret = getattr(request.state, "jwt_secret", None)
        # Slide the expiry forward for anyone still playing, so an active
        # guest never loses their identity to a lapsed token.
        if token and secret and should_refresh(token, secret):
            await issue_cookie(response, request, user.id)
        return user_payload(refreshed or user)

    @router.get("/nickname-available")
    async def nickname_available(request: Request, name: str = ""):
        """Whether a guest may play under this name."""
        throttle(lookup_limiter, request)
        try:
            candidate = validate_name(name)
        except NameError_ as error:
            return {"available": False, "reason": str(error)}
        owner = await user_repo.get_by_username(candidate)
        if owner is not None and not owner.is_anonymous:
            return {
                "available": False,
                "reason": "That name belongs to a registered player.",
            }
        return {"available": True, "reason": None}

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
            raise HTTPException(status_code=400, detail=str(error)) from error
        try:
            password = validate_password(body.password)
        except PasswordPolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        user_id = getattr(request.state, "user_id", None)
        current = await user_repo.get_by_id(user_id) if user_id else None
        if current is not None and not current.is_anonymous:
            raise HTTPException(
                status_code=409, detail="You are already signed in to an account."
            )

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

        await user_repo.touch_last_login(claimed.id)
        await issue_cookie(response, request, claimed.id)
        return user_payload(claimed)

    @router.post("/login")
    async def login(body: CredentialsBody, request: Request, response: Response):
        """Sign in to an existing account.

        Any guest identity the caller was carrying is left behind: its stats
        stay with that abandoned row. Registering rather than logging in is the
        path that carries guest progress forward.
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

        refreshed = await user_repo.touch_last_login(credentials.user.id)
        await issue_cookie(response, request, credentials.user.id)
        return user_payload(refreshed or credentials.user)

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        """Drop the session. The next /me call provisions a fresh guest."""
        clear_session_cookie(response, secure=is_secure_request(request))
        return {"ok": True}

    return router
