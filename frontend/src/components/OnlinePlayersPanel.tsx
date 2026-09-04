import { useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { sessionFrom } from "../lib/roomEntryState";
import { emitWithAck } from "../lib/socket";
import { friendActionFor, isFriend, withFriendsFirst } from "../lib/friends";
import { presenceSummary } from "../lib/lobbyPresence";
import type { OnlinePlayer } from "../lib/lobbyPresence";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { useGameStore } from "../store/gameStore";
import { usePresenceStore } from "../store/presenceStore";
import { useToast } from "../lib/toast";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { PlusIcon } from "./icons";
import type { AckResponse } from "../types";

/** Who else is here, beside the room list.

A plain list rather than something to open: at the lobby's scale it fits on
screen, and the whole value of it is being readable without a click.

There is deliberately no filter. The list is capped, so a filter over it would
answer "no such player" about somebody who is online — and nobody scans a list
this size by typing anyway. Finding a specific person is a different feature
from seeing who is around, and it needs a server-side lookup rather than a text
box over the rows that happened to fit. */
export function OnlinePlayersPanel() {
  const presence = usePresenceStore((state) => state.presence);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);
  const iAmAGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  const lists = useFriendsStore((state) => state.lists);
  const pending = useFriendsStore((state) => state.pending);
  const addFriend = useFriendsStore((state) => state.add);
  const acceptRequest = useFriendsStore((state) => state.accept);
  const declineRequest = useFriendsStore((state) => state.remove);
  const { notify } = useToast();
  const navigate = useNavigate();
  const setSession = useGameStore((state) => state.setSession);

  // Friends first, then the order the server sent — see `withFriendsFirst`.
  const players = useMemo(
    () => withFriendsFirst(presence.players, lists),
    [presence.players, lists],
  );

  // Somebody who has asked to be friends but is not online has nowhere else to
  // appear, so the requests ride above the list rather than inside it.
  const offlineRequests = useMemo(
    () =>
      lists.incoming.filter(
        (entry) => !presence.players.some((p) => p.userId === entry.userId),
      ),
    [lists.incoming, presence.players],
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

      {offlineRequests.length > 0 && (
        <ul className="online-players-list online-requests" data-testid="friend-requests">
          {offlineRequests.map((entry) => (
            <li key={entry.userId} className="online-player-row is-request">
              <Avatar
                name={entry.displayName}
                nameColor={entry.nameColor ?? undefined}
                avatarUrl={entry.avatarUrl}
                isAnonymous={entry.isAnonymous}
                size={28}
              />
              <span className="online-player-name">{entry.displayName}</span>
              <span className="online-player-actions">
                <Button
                  variant="primary"
                  compact
                  disabled={pending === entry.userId}
                  onClick={() => void acceptRequest(entry.userId)}
                >
                  Accept
                </Button>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  disabled={pending === entry.userId}
                  onClick={() => void declineRequest(entry.userId)}
                >
                  Decline
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {players.length === 0 && offlineRequests.length === 0 ? (
        <p className="online-players-empty">Nobody else is here right now.</p>
      ) : (
        <ul className="online-players-list" data-testid="online-players-list">
          {players.map((player) => {
            const action = iAmAGuest
              ? "none"
              : friendActionFor(player, lists, myUserId);
            const theyAreAFriend = isFriend(lists, player.userId);
            const busy = pending === player.userId;
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
                <span
                  className={`online-player-name${player.isAnonymous ? " is-guest" : ""}`}
                  style={
                    player.isAnonymous || !player.nameColor
                      ? undefined
                      : { color: player.nameColor }
                  }
                >
                  {player.displayName}
                </span>

                <span className="online-player-actions">
                  {action === "add" && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-compact online-add-friend"
                      disabled={busy}
                      title={`Add ${player.displayName} as a friend`}
                      aria-label={`Add ${player.displayName} as a friend`}
                      onClick={() => void addFriend(player.userId)}
                    >
                      <PlusIcon size={14} />
                    </button>
                  )}
                  {action === "accept" && (
                    <Button
                      variant="primary"
                      compact
                      disabled={busy}
                      onClick={() => void acceptRequest(player.userId)}
                    >
                      Accept
                    </Button>
                  )}
                  {action === "sent" && (
                    <span className="online-player-status">Request sent</span>
                  )}
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
