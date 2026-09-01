"""The route table this server keeps, against the one the client actually has.

`app/client_routes.py` exists so an unmatched URL can answer 404 instead of a
soft 200, which means it is a second copy of the `<Route>` list in
`frontend/src/App.tsx`. Two copies drift, and this one drifts silently in the
direction that matters: a route added to the client alone renders perfectly in
a browser while answering 404 to every crawler, link checker and uptime probe.
Nothing in either language would notice.

So this reads `App.tsx` as text and refuses any difference. It matches string
literals rather than running the router - fast, dependency-free, and blind to
semantics - which is the same trade `test_wire_contract.py` makes for the
socket vocabulary. Adding or renaming a route stays easy: change both lists in
one commit and this goes quiet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.client_routes import CLIENT_ROUTES, is_client_route

APP_TSX = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "App.tsx"
)


def declared_client_routes() -> set[str]:
    source = APP_TSX.read_text(encoding="utf-8")
    return set(re.findall(r'<Route\s+path="([^"]+)"', source))


def test_the_two_route_tables_are_the_same_list():
    declared = declared_client_routes()
    # The catch-all is what renders the not-found page, so it is deliberately
    # not a "known" route here - counting it would make every URL known.
    assert declared - {"*"} == set(CLIENT_ROUTES)


def test_the_client_has_a_catch_all_to_render():
    # Without it an unknown URL is served the shell, answers 404, and draws
    # nothing at all - which is the blank page this whole change removes.
    assert "*" in declared_client_routes()


def test_app_tsx_is_where_this_thinks_it_is():
    # A moved or renamed file would empty the set above and pass everything
    # vacuously, which is the one way this guard could fail open.
    assert APP_TSX.is_file()
    assert declared_client_routes()


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/create",
        # react-router ignores a trailing slash, so answering 404 for one
        # would be a difference nobody typed.
        "/create/",
        "/room/ABC123",
        "/prompt-lists",
        "/prompt-lists/english-standard",
        "/my-prompt-lists",
        "/profile",
        "/profile/0193f0c1-2b3d-7e00-8a11-6f9c0d2e4b5a",
        "/forgot-password",
        "/reset-password",
        "/verify-email",
        "/admin/operations",
        "/moderation",
        "/admin/bug-reports",
    ],
)
def test_a_page_the_client_has_is_a_client_route(path):
    assert is_client_route(path)


@pytest.mark.parametrize(
    "path",
    [
        "/nope",
        "/lobbyy",
        # A parameter needs a value: this is the room list, and there is none.
        "/room/",
        "/room/ABC123/extra",
        "/profile/someone/games",
        "/admin",
        "/admin/operations/tuning",
        "/prompt-lists/english-standard/prompts",
        "/verify-emails",
    ],
)
def test_a_page_the_client_does_not_have_is_not_a_client_route(path):
    assert not is_client_route(path)
