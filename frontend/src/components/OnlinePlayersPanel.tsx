import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";

import { sessionFrom } from "../lib/roomEntryState";
import { emitWithAck } from "../lib/socket";
import { isFriend, withFriendsFirst } from "../lib/friends";
import { presenceSummary } from "../lib/lobbyPresence";
import type { OnlinePlayer } from "../lib/lobbyPresence";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { useGameStore } from "../store/gameStore";
import { usePresenceStore } from "../store/presenceStore";
import { useToast } from "../lib/toast";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import type { AckResponse } from "../types";

/** Who else is here, beside the room list.

A plain list rather than something to open: at the lobby's scale it fits on
screen, and the whole value of it is being readable without a click.

**Presence only.** It says who is around and what they are doing, and carries
no friendship state at all — no way to ask, and no report of a request in
either direction. Those lived here when there was nowhere else for them, and
a row in this list is the wrong home for either: it comes and goes as people
open and close tabs, so an offer to ask was available one second and gone the
next, and a request it reported was answerable only while its sender happened
to still be standing there. Asking is on the profile every name links to;
answering is on the friends surface, whether or not the other person is online
(R-FRIEND-10, R-FRIEND-11). What survives is *Join*, which is about a friend's
game rather than about the friendship.

There is deliberately no filter. The list is capped, so a filter over it would
answer "no such player" about somebody who is online — and nobody scans a list
this size by typing anyway. Finding a specific person is a different feature
from seeing who is around: it is the profile, reached from a name here or from
a game's participant list. */
export function OnlinePlayersPanel() {
  const presence = usePresenceStore((state) => state.presence);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);
  const lists = useFriendsStore((state) => state.lists);
  const { notify } = useToast();
  const navigate = useNavigate();
  const setSession = useGameStore((state) => state.setSession);

  // Friends first, then the order the server sent — see `withFriendsFirst`.
  const players = useMemo(
    () => withFriendsFirst(presence.players, lists),
    [presence.players, lists],
  );

  async function joinFriend(player: OnlinePlayer) {
    try {
      const answer = await emitWithAck<AckResponse>("join_friend_room", {
        friendUserId: player.userId,
      });
      const session = sessionFrom(answer);
      if (!session) {
        notify(answer?.error ?? "Could not join that game.");
        return;
      }
      // The seat is already taken by the time this answers, so the page has
      // to follow it - otherwise the player is in a room the screen is not.
      setSession(session);
      navigate(`/room/${session.code}`);
    } catch {
      notify("Could not join that game.");
    }
  }

  return (
    <section className="panel lobby-online-panel" aria-labelledby="online-heading">
      <div className="lobby-rooms-heading">
        <h2 id="online-heading">Who is online</h2>
        {/* The true total, not the number of rows: a cap must never read as a
            quiet server (R-PRESENCE-04). */}
        <span className="lobby-rooms-count">{presenceSummary(presence)}</span>
      </div>

      {players.length === 0 ? (
        <p className="online-players-empty">Nobody else is here right now.</p>
      ) : (
        <ul className="online-players-list" data-testid="online-players-list">
          {players.map((player) => {
            const theyAreAFriend = isFriend(lists, player.userId);
            return (
              <li
                key={player.userId}
                className={`online-player-row${player.userId === myUserId ? " is-me" : ""}${theyAreAFriend ? " is-friend" : ""}`}
              >
                <Avatar
                  name={player.displayName}
                  nameColor={player.nameColor ?? undefined}
                  avatarUrl={player.avatarUrl}
                  isAnonymous={player.isAnonymous}
                  size={28}
                />
                {/* The name is a link, because presence already carries the
                    account id — R-ROOM-07 carves that out for the lobby
                    precisely because a friend request needs a stable target.
                    A guest has no profile worth opening: their identity is a
                    browser, so the name stays plain text for them. */}
                {player.isAnonymous ? (
                  <span className="online-player-name is-guest">
                    {player.displayName}
                  </span>
                ) : (
                  <Link
                    to={`/profile/${player.userId}`}
                    className="online-player-name"
                    style={player.nameColor ? { color: player.nameColor } : undefined}
                  >
                    {player.displayName}
                  </Link>
                )}

                <span className="online-player-actions">
                  {/* Only a friend gets a way in, and only when there is
                      something to join. Everyone else's row says where they
                      are and stops there. */}
                  {theyAreAFriend && player.status === "playing" ? (
                    <Button
                      variant="secondary"
                      compact
                      onClick={() => void joinFriend(player)}
                    >
                      Join
                    </Button>
                  ) : (
                    <span className={`online-player-status is-${player.status}`}>
                      {player.status === "playing" ? "In a game" : "In the lobby"}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
