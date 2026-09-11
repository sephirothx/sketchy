"""The REST refusal contract: a code for the player, prose for the log.

Two rules, and both need a test because neither compiler checks them.

**The server names its refusals.** A player-facing route raises `Refusal`,
which carries an enumerated `errorCode`; a staff-only route may still raise a
plain `HTTPException`, because the moderation queue and the operations pages
are read by operators in one language and an audit trail that reads
differently depending on who opened it is worse than one that is always
English (R-I18N-01).

**The client writes the sentence.** `detail` and the acknowledgement's `error`
still cross the wire - a log line, a bug report and an operator reading a
response by hand all want them - and nothing renders them. That is the half a
type checker cannot see: `error.message` is a perfectly good string, and
printing it is how the server became the author of text a player reads.
That half is checked where the tree can be parsed:
`frontend/tests/serverProse.test.mjs` accounts for every read of the server's
prose on a player-facing screen.

The staff allowlist below is the split itself, written down. A new
`HTTPException` in a player-facing route fails here, and the fix is either to
raise `Refusal` or to add the route to the list on purpose.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_APP = REPO_ROOT / "backend" / "app"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# (module, enclosing function) pairs that may still refuse with prose. Every
# one is reached only by a moderator or an administrator.
STAFF_ONLY = {
    ("api/admin_auth.py", "require_admin"),
    ("api/admin_controls.py", "_room_or_404"),
    ("api/admin_controls.py", "end_turn"),
    ("api/admin_controls.py", "initiate_shutdown"),
    ("api/admin_controls.py", "kick_player"),
    ("api/admin_controls.py", "set_maintenance"),
    ("api/admin_controls.py", "set_role"),
    ("api/admin_settings.py", "change_tunables"),
    ("api/bug_reports.py", "bug_report_screenshot"),
    ("api/bug_reports.py", "list_bug_reports"),
    ("api/bug_reports.py", "review_bug_report"),
    ("api/moderation.py", "_attach_and_resolve_report"),
    ("api/moderation.py", "_lock_pending_content_incident"),
    ("api/moderation.py", "_lock_pending_incident"),
    ("api/moderation.py", "_reviewer"),
    ("api/moderation.py", "create_ban"),
    ("api/moderation.py", "create_warning"),
    ("api/moderation.py", "remove_reported_avatar"),
    ("api/moderation.py", "review_prompt_content_report"),
    ("api/moderation.py", "read_held_publication"),
    ("api/moderation.py", "review_publication"),
    ("api/moderation.py", "revoke_ban"),
    ("api/operations.py", "player_activity"),
    ("api/operations.py", "scrape"),
}

# Screens only an operator opens. They are English on purpose and the scan
# below leaves them alone.
STAFF_SCREENS = (
    "pages/ops/",
    "pages/AdminOperationsPage",
    "pages/ModerationPage",
    "pages/BugReportsPage",
)


class _Visitor(ast.NodeVisitor):
    """Collect `HTTPException(...)` sites, remembering the function each is in."""

    def __init__(self, module: str, sites: set[tuple[str, str]]) -> None:
        self.module = module
        self.sites = sites
        self.stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "HTTPException":
            self.sites.add((self.module, self.stack[-1] if self.stack else "<module>"))
        self.generic_visit(node)


def _http_exception_sites() -> set[tuple[str, str]]:
    """Every `HTTPException(...)` under `app/api` and `app/auth`, by function."""
    sites: set[tuple[str, str]] = set()
    for path in sorted(
        list((BACKEND_APP / "api").glob("*.py")) + list((BACKEND_APP / "auth").glob("*.py"))
    ):
        module = f"{path.parent.name}/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _Visitor(module, sites).visit(tree)
    return sites


def test_only_staff_routes_refuse_with_prose():
    """A player-facing refusal carries a code, or the client cannot translate it."""
    sites = _http_exception_sites()
    unnamed = sorted(sites - STAFF_ONLY)
    assert not unnamed, (
        "these refusals reach a player as prose with no errorCode: "
        f"{unnamed}. Raise `Refusal(status, ErrorCode.X, ...)` instead, or add "
        "the route to STAFF_ONLY if only an operator can reach it."
    )


def test_the_staff_allowlist_has_no_dead_entries():
    """An entry for a route that no longer refuses is a stale exemption.

    Worse than none: it silently covers whatever is written there next.
    """
    stale = sorted(STAFF_ONLY - _http_exception_sites())
    assert not stale, f"STAFF_ONLY names routes that raise no HTTPException: {stale}"


def _player_facing_sources() -> list[tuple[Path, str]]:
    return [
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(FRONTEND_SRC.rglob("*.ts*"))
        if not any(str(path.relative_to(FRONTEND_SRC)).startswith(s) for s in STAFF_SCREENS)
    ]



def test_the_client_has_a_sentence_for_every_code():
    """The catalogue is exhaustive over `ErrorCode`, and the compiler proves it.

    `Record<ErrorCode, …>` is what does the proving, so this only checks the
    declaration is still written that way - a widened type would let a new
    server code reach a player as a blank with nothing failing. The sentences
    live with every other word the interface says (#762), so a locale
    translates them in the same pass as the rest.
    """
    source = (FRONTEND_SRC / "content" / "ui" / "en.ts").read_text(encoding="utf-8")
    assert "const REFUSALS: Record<ErrorCode, Sentence>" in source, (
        "the catalogue must declare REFUSALS as Record<ErrorCode, Sentence>, so "
        "a code with no sentence fails the build rather than the player."
    )
