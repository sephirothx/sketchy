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
"""
from __future__ import annotations


# Mirrors the <Route path=...> list in frontend/src/App.tsx, in its order.
# The catch-all (path="*") is deliberately absent: it is what *renders* the
# not-found page, so treating it as a known route would defeat the whole list.
CLIENT_ROUTES: tuple[str, ...] = (
    "/",
    "/create",
    "/room/:code",
    "/prompt-lists",
    "/prompt-lists/:slug",
    "/my-prompt-lists",
    "/profile",
    "/profile/:userId",
    "/settings",
    "/settings/:section",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/admin/operations",
    "/moderation",
    "/admin/bug-reports",
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


def is_client_route(path: str) -> bool:
    """Whether the SPA has a page for *path*.

    Takes the URL as the browser asked for it, not the filesystem path
    `StaticFiles` derives from it - that one normalizes the root to "." and
    would never match anything here.

    A trailing slash is ignored, because react-router ignores it: "/create/"
    and "/create" are one page, and answering 404 for one of them would be a
    difference nobody typed.
    """
    trimmed = path.rstrip("/") or "/"
    segments = trimmed.split("/")
    return any(_matches(route, segments) for route in CLIENT_ROUTES)
