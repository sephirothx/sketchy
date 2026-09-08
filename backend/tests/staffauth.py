"""Signing a staff account all the way in, second factor included.

R-AUTH-20 makes a moderator or administrator account unusable until it has
enrolled a second factor, and R-AUTH-21 makes every destructive action ask for
it again inside a short window. Every test that exercises a staff surface
therefore has to do what a real moderator does, and doing it by hand in each
file would be six lines of TOTP arithmetic repeated a dozen times.

Deliberately drives the real endpoints rather than writing rows: the point of
these helpers is that the gate they walk through is the one a browser walks
through, so a change that breaks enrolment breaks these too.
"""
from __future__ import annotations

import time

from httpx import AsyncClient

from app.auth.totp import code_at, current_step


async def enrol_second_factor(
    client: AsyncClient, password: str = "a-good-password"
) -> str:
    """Complete enrolment for the signed-in account; return its secret.

    The password goes with it: binding a second factor proves it, because the
    row is later taken as evidence that the account's owner holds the factor
    (R-AUTH-20).
    """
    offer = await client.post("/api/auth/second-factor/enrol")
    assert offer.status_code == 200, offer.text
    secret = offer.json()["secret"]
    confirmed = await client.post(
        "/api/auth/second-factor/confirm",
        json={
            "secret": secret,
            "code": code_at(secret, current_step(time.time())),
            "password": password,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret


async def step_up(client: AsyncClient, secret: str) -> None:
    """Prove the second factor for this session's short window.

    Uses the *next* step's code, not this one's. Enrolment and any earlier
    step-up have already spent the current interval, and a spent code is
    refused on purpose - which is exactly the replay protection under test
    elsewhere. One step ahead is inside the drift the verifier allows.
    """
    code = code_at(secret, current_step(time.time()) + 1)
    response = await client.post("/api/auth/step-up", json={"code": code})
    assert response.status_code == 200, response.text


async def staff_ready(client: AsyncClient) -> str:
    """Enrol and step up in one call, for a client about to act as staff."""
    secret = await enrol_second_factor(client)
    await step_up(client, secret)
    return secret


async def mark_staff_ready(factory, user_id) -> None:
    """Satisfy R-AUTH-20 and R-AUTH-21 for a test that is not about them.

    Writes the enrolment row and stamps a live step-up onto every session the
    account holds, which is what the two endpoints above do through HTTP.

    Used by the suites whose subject is moderation or operator behaviour
    rather than authentication: making twenty tests about suspending an
    account also walk an enrolment ceremony would bury what each of them is
    for. The ceremony itself, and the refusal when it has not happened, are
    covered against the real endpoints in `test_auth_hardening.py` and
    `test_admin_controls.py`.
    """
    from datetime import datetime, timezone
    from uuid import UUID

    from sqlalchemy import update

    from app.db.models import AuthSession, UserSecondFactor

    now = datetime.now(timezone.utc)
    target = UUID(str(user_id))
    async with factory() as session:
        async with session.begin():
            if await session.get(UserSecondFactor, target) is None:
                session.add(
                    UserSecondFactor(
                        user_id=target,
                        secret="JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
                        confirmed_at=now,
                        created_at=now,
                        last_step=0,
                        failed_attempts=0,
                    )
                )
            await session.execute(
                update(AuthSession)
                .where(
                    AuthSession.user_id == target,
                    AuthSession.revoked_at.is_(None),
                )
                .values(stepped_up_at=now)
            )
