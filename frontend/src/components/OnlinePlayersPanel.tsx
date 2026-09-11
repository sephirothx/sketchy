import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { sessionFrom } from "../lib/roomEntryState";
import { emitWithAck } from "../lib/socket";
import { isFriend, lobbyRowMayOfferFriendship, withFriendsFirst } from "../lib/friends";
import { presenceSummary } from "../lib/lobbyPresence";
import type { OnlinePlayer } from "../lib/lobbyPresence";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { useGameStore } from "../store/gameStore";
import { usePresenceStore } from "../store/presenceStore";
import { useToast } from "../lib/toast";
import { Avatar } from "./ui/Avatar";
import { LobbyPlayerMenu } from "./LobbyPlayerMenu";
import { ReportAccountDialog } from "./ReportAccountDialog";
import { Button } from "./ui/Button";
import type { AckResponse } from "../types";
import { ui } from "../content/ui/index.ts";
import { refusalText } from "../lib/refusals.ts";

/** Who else is here, beside the room list.

A plain list rather than something to open: at the lobby's scale it fits on
screen, and the whole value of it is being readable without a click.

**No request state.** It says who is around and what they are doing, and never
reports a request in either direction — a row comes and goes as people open and
close tabs, so a request reported on one was answerable only while its sender
happened to still be standing there. Answering is on the friends surface,
whether or not the other person is online
(R-FRIEND-10, R-FRIEND-11). *Join* is here because it is about a friend's game
rather than about the friendship, and each row's menu offers what can be done
about the person on it: their profile, a friendship, a report.

There is deliberately no filter. The list is capped, so a filter over it would
answer "no such player" about somebody who is online — and nobody scans a list
this size by typing anyway. Finding a specific person is a different feature
from seeing who is around: it is the profile, reached from a row's menu here or
from a game's participant list. */
export function OnlinePlayersPanel() {
  const presence = usePresenceStore((state) => state.presence);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);
  const iAmAGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  const lists = useFriendsStore((state) => state.lists);
  const addFriend = useFriendsStore((state) => state.add);
  const { notify } = useToast();
  const navigate = useNavigate();
  const setSession = useGameStore((state) => state.setSession);
  const [openMenuFor, setOpenMenuFor] = useState<string | null>(null);
  const [reporting, setReporting] = useState<{
    userId: string;
    displayName: string;
    avatarUrl: string | null;
  } | null>(null);
  // The viewer, in the shape the friendship rules take it.
  const me = myUserId ? { userId: myUserId, isAnonymous: iAmAGuest } : null;

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
        notify(refusalText(answer, ui.onlinePlayersPanel.couldNotJoinThatGame));
        return;
      }
      // The seat is already taken by the time this answers, so the page has
      // to follow it - otherwise the player is in a room the screen is not.
      setSession(session);
      navigate(`/room/${session.code}`);
    } catch {
      notify(ui.onlinePlayersPanel.couldNotJoinThatGame);
    }
  }

  return (
    <section className="panel lobby-online-panel" aria-labelledby="online-heading">
      <div className="lobby-rooms-heading">
        <h2 id="online-heading">{ui.onlinePlayersPanel.whoOnline}</h2>
        {/* The true total, not the number of rows: a cap must never read as a
            quiet server (R-PRESENCE-04). */}
        <span className="lobby-rooms-count">{presenceSummary(presence)}</span>
      </div>

      {players.length === 0 ? (
        <p className="online-players-empty">{ui.onlinePlayersPanel.nobodyElseHereRightNow}</p>
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
                  isFriend={theyAreAFriend}
                  size={28}
                />
                {/* The disc's mark is decorative, so the name carries the
                    word - beside it rather than inside the name itself,
                    which is the player's and nothing else. */}
                {theyAreAFriend && <span className="visually-hidden">{ui.onlinePlayersPanel.friend}</span>}
                {/* A guest has no profile worth opening, nothing to befriend
                    and no account to report: their identity is a browser, so
                    their name stays plain text and the row offers nothing.
                    Your own row offers nothing either. */}
                {player.isAnonymous || player.userId === myUserId ? (
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
                ) : (
                  <LobbyPlayerMenu
                    userId={player.userId}
                    displayName={player.displayName}
                    isOpen={openMenuFor === player.userId}
                    onOpenChange={(open) =>
                      setOpenMenuFor(open ? player.userId : null)
                    }
                    onAddFriend={
                      lobbyRowMayOfferFriendship(
                        { userId: player.userId, isAnonymous: player.isAnonymous },
                        lists,
                        me,
                      )
                        ? () => void addFriend(player.userId)
                        : null
                    }
                    onReport={
                      iAmAGuest
                        ? null
                        : () =>
                            setReporting({
                              userId: player.userId,
                              displayName: player.displayName,
                              avatarUrl: player.avatarUrl ?? null,
                            })
                    }
                  >
                    <span
                      className="online-player-name"
                      style={player.nameColor ? { color: player.nameColor } : undefined}
                    >
                      {player.displayName}
                    </span>
                  </LobbyPlayerMenu>
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
                      {ui.onlinePlayersPanel.join}
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
      {reporting && (
        <ReportAccountDialog
          userId={reporting.userId}
          displayName={reporting.displayName}
          avatarUrl={reporting.avatarUrl}
          onClose={() => setReporting(null)}
        />
      )}
    </section>
  );
}
