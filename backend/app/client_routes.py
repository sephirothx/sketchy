"""The URLs the bundled client has a page for.

The SPA is one HTML file, so every client route is served the same shell. That
makes the shell the only thing a machine ever sees, and without this list every
misspelled or dead URL would answer 200 - a "soft 404" that tells a crawler, a
link checker or an uptime probe that a page exists where none does. The list
below is what lets `SPAStaticFiles` serve the shell (so React can draw the
not-found page) while still answering 404.

It is a second copy of the route table in `frontend/src/App.tsx`, and a second
copy is a thing that drifts. The drift is silent in the direction that matters:
add a route there and forget it here, and the page renders perfectly in a
browser while answering 404 to everything that is not one. So the ``:param``
syntax is react-router's, kept verbatim, and `tests/test_client_routes.py`
reads `App.tsx` and refuses any difference between the two lists.

Each route also says whether a search engine may index it (#1458), in the
same table, so adding a page means deciding that too.
"""
from __future__ import annotations


# Mirrors the <Route path=...> list in frontend/src/App.tsx, in its order,
# each with whether a search engine may index it (#1458). One table, so a new
# route cannot be added without that being decided: the indexable ones are the
# public pages somebody could search for, and everything else answers with
# `X-Robots-Tag: noindex` (`app/seo.py`).
#
# - The lobby, the rules, the legal pages, Solo and the official word lists
#   are public, need no session and say the same thing to everybody.
# - The community catalogue is public too (R-LIST-19), but user-authored: a
#   takedown (R-LIST-13) cannot recall a search engine's cached snippet, so
#   it waits for a trust threshold (#1463).
# - The Gallery refuses a visitor without a session (R-GAL-02), so all a
#   crawler could index is the refusal.
# - Rooms are ephemeral and their names are not ours to publish (N-06's
#   spirit); profiles, settings, friends, account recovery and the staff
#   pages are personal or private.
#
# The catch-all (path="*") is deliberately absent: it is what *renders* the
# not-found page, so treating it as a known route would defeat the whole list.
CLIENT_ROUTE_TABLE: tuple[tuple[str, bool], ...] = (
    ("/", True),
    ("/create", False),
    ("/room/:code", False),
    ("/rules", True),
    ("/privacy", True),
    ("/terms", True),
    ("/prompt-lists", True),
    ("/prompt-lists/:slug", True),
    ("/community-lists", False),
    ("/community-lists/:listId", False),
    ("/gallery", False),
    ("/gallery/:turnId", False),
    ("/solo", True),
    ("/my-prompt-lists", False),
    ("/profile", False),
    ("/profile/:userId", False),
    ("/settings", False),
    ("/settings/:section", False),
    ("/friends", False),
    ("/forgot-password", False),
    ("/reset-password", False),
    ("/verify-email", False),
    ("/admin/operations", False),
    ("/moderation", False),
    ("/admin/bug-reports", False),
)

CLIENT_ROUTES: tuple[str, ...] = tuple(route for route, _ in CLIENT_ROUTE_TABLE)
INDEXABLE_ROUTES: tuple[str, ...] = tuple(
    route for route, indexable in CLIENT_ROUTE_TABLE if indexable
)


def _matches(route: str, segments: list[str]) -> bool:
    expected = route.split("/")
    if len(expected) != len(segments):
        return False
    return all(
        # A parameter matches any one segment that is actually there. An empty
        # one is not a value: "/room/" is the room list, which does not exist,
        # rather than a room whose code is the empty string.
        (part[1:] and actual != "")
        if part.startswith(":")
        # Case-folded, because react-router is: a `<Route>` matches
        # case-insensitively unless it sets `caseSensitive`, and none of ours
        # do - so /Create renders the create page, and answering 404 for it
        # would be the mismatch this module exists to prevent. `lower()`
        # rather than `casefold()`, which folds harder than a JS regexp's `i`
        # does and would claim URLs the client does not actually match.
        else part.lower() == actual.lower()
        # strict: the length check above already guarantees equal lengths.
        for part, actual in zip(expected, segments, strict=True)
    )


def _segments(path: str) -> list[str]:
    return (path.rstrip("/") or "/").split("/")


def is_client_route(path: str) -> bool:
    """Whether the SPA has a page for *path*.

    Takes the URL as the browser asked for it, not the filesystem path
    `StaticFiles` derives from it - that one normalizes the root to "." and
    would never match anything here.

    A trailing slash is ignored, because react-router ignores it: "/create/"
    and "/create" are one page, and answering 404 for one of them would be a
    difference nobody typed.
    """
    segments = _segments(path)
    return any(_matches(route, segments) for route in CLIENT_ROUTES)


def is_indexable_route(path: str) -> bool:
    """Whether *path* is a client page a search engine may index (#1458).

    Matched the way `is_client_route` matches, so a trailing slash or a
    capital letter does not turn a public page private or the reverse.
    """
    segments = _segments(path)
    return any(_matches(route, segments) for route in INDEXABLE_ROUTES)
