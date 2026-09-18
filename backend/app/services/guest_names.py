"""One guest name per person online (R-ACCT-09).

A registered player's name is unique because it is their username. A guest's
name was unique against usernames and nothing else, so two guests could sit in
the lobby's online list, the chat and even one room as the same "asd", and
nobody could tell which was which.

It is not made unique the way a username is. Guest accounts are never deleted,
so a name taken for good by every guest who ever chose it would use up "Alex"
within a week. What matters is the people a player can see, so the rule is
about who is online: a guest may not choose a name another online guest is
using, and the name comes free when its holder has been gone for longer than a
reload (`ARRIVAL_GRACE_SECONDS`).

That leaves one way two online guests can share a name: one of them chose it
while the other was away, and the other came back. Whoever arrived first keeps
it - arrival is `PresenceRegistry.arrival_of`, which a reload does not reset -
and the one who arrived second is asked for a new name before they can take a
seat or speak in the lobby, and is left out of the online list until they have
one.
"""
from __future__ import annotations

from app.auth.names import fold_guest_name
from app.repositories.interfaces import UserRepository
from app.services.presence import PresenceIdentityCache, PresenceRegistry


async def online_guest_holding(
    name: str,
    *,
    claimant_id: str | None,
    registry: PresenceRegistry | None,
    user_repo: UserRepository | None,
    choosing: bool,
    identities: PresenceIdentityCache | None = None,
) -> str | None:
    """The online guest who holds `name` against `claimant_id`, if any.

    `choosing` is a guest picking a name: every other online guest under it
    holds it. Otherwise it is a guest already under that name, who holds it
    unless somebody else online under it arrived first. A guest with no
    arrival - offline for longer than a reload - arrives after everybody
    already here.

    Answered from `identities` - the lobby list's cache of every online
    account's name, warmed at the handshake and invalidated by every path
    that writes a name or turns a guest into an account - and from the
    database only for the ids it cannot answer (#900). Sending every online
    id to the database on each guest chat line cost 6-10 ms at a thousand
    online, on the one event loop every room runs on.
    """
    if registry is None or user_repo is None:
        return None
    # Somebody who left moments ago - a reload, a dropped connection - still
    # holds their name, so it cannot be chosen out from under them.
    online = registry.online_user_ids() + registry.recently_departed_ids()
    arrival = None if choosing else registry.arrival_of(claimant_id)
    if arrival is not None:
        online = [
            user_id for user_id in online
            if (registry.arrival_of(user_id) or 0) < arrival
        ]
    among = [user_id for user_id in online if user_id != claimant_id]
    if not among:
        return None
    unknown = among
    if identities is not None:
        folded = fold_guest_name(name.strip())
        known = identities.cached(among)
        for user_id in among:
            identity = known.get(user_id)
            if (
                identity is not None
                and identity.is_anonymous
                and fold_guest_name(identity.display_name) == folded
            ):
                return user_id
        unknown = [user_id for user_id in among if user_id not in known]
        if not unknown:
            return None
    return await user_repo.find_guest_named(name, unknown)
