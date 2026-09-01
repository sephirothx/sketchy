import { presenceSummary } from "../lib/lobbyPresence";
import { useAuthStore } from "../store/authStore";
import { usePresenceStore } from "../store/presenceStore";
import { Avatar } from "./ui/Avatar";

/** Who else is here, beside the room list.

A plain list rather than something to open: at the lobby's scale it fits on
screen, and the whole value of it is being readable without a click.

There is deliberately no filter. The list is capped, so a filter over it would
answer "no such player" about somebody who is online — and nobody scans a list
this size by typing anyway. Finding a specific person is a different feature
from seeing who is around, and it needs a server-side lookup rather than a
text box over the rows that happened to fit. */
export function OnlinePlayersPanel() {
  const presence = usePresenceStore((state) => state.presence);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);

  return (
    <section className="panel lobby-online-panel" aria-labelledby="online-heading">
      <div className="lobby-rooms-heading">
        <h2 id="online-heading">Who is online</h2>
        {/* The true total, not the number of rows: a cap must never read as a
            quiet server (R-PRESENCE-04). */}
        <span className="lobby-rooms-count">{presenceSummary(presence)}</span>
      </div>

      {presence.players.length === 0 ? (
        <p className="online-players-empty">Nobody else is here right now.</p>
      ) : (
        <ul className="online-players-list" data-testid="online-players-list">
          {presence.players.map((player) => (
            <li
              key={player.userId}
              className={`online-player-row${player.userId === myUserId ? " is-me" : ""}`}
            >
              <Avatar
                name={player.displayName}
                nameColor={player.nameColor ?? undefined}
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
              <span className={`online-player-status is-${player.status}`}>
                {player.status === "playing" ? "In a game" : "In the lobby"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
