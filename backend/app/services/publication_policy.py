"""Whether a newly published community list waits for a moderator.

The one stored value behind R-LIST-13. It lives in a module of its own rather
than beside the endpoint that sets it, because the endpoint that *reads* it is
in the prompt-list router and the one that writes it is in the administrative
one - and importing the second from the first drags the room manager and the
shutdown coordinator into a module that needs neither.

Post-hoc moderation is the posture this switch exists to make reversible.
Community content is reviewed after a report (#378) rather than before
publication, because an approval queue in a single-operator deployment (N-01,
N-12) makes the catalogue's contents depend on the scarcest resource here, and
because pre-approval fights R-LIST-05: editing writes a new immutable revision,
so approval would have to attach to revisions and every metadata change would
drop a list out of the catalogue until staff cleared it again.

Turning this on is therefore not a small configuration change. It is the
deployment saying the accepted cost - the window between a publish and the
first report - has stopped being acceptable.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import config_store

PUBLICATION_REVIEW_KEY = "prompt_lists.publication_review"
PUBLICATION_REVIEW_EVENT = "prompt_lists.publication_review_changed"


async def read_publication_review(
    session_factory: async_sessionmaker[AsyncSession],
) -> bool:
    """Whether a list published from now on lands `under_review`.

    Read per publish rather than cached. Publishing is rare and rate-limited,
    and a cached posture is one that can be stale at the moment it matters
    most - just after an operator turned it on because something is going
    wrong.
    """
    return (
        await config_store.read_one(session_factory, PUBLICATION_REVIEW_KEY) == "1"
    )
