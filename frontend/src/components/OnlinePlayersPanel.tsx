import { useMemo, useState } from "react";

import { filterPlayers, presenceSummary } from "../lib/lobbyPresence";
import { usePresenceStore } from "../store/presenceStore";
import { Avatar } from "./ui/Avatar";
import { BottomSheet } from "./ui/BottomSheet";
import { SearchIcon } from "./icons";

/** How many faces the strip shows before it becomes a count.

Enough to read the room at a glance on a phone without the strip wrapping;
everyone else is behind the tap. */
const FACES_ON_THE_STRIP = 8;

function StatusLabel({ status }: { status: "lobby" | "playing" }) {
  return (
    <span className={`online-player-status is-${status}`}>
      {status === "playing" ? "In a game" : "In the lobby"}
    </span>
  );
}

/** Who else is here, as a strip that opens into the full list.

A strip rather than a list because the lobby's job is the room browser, and
400 rows above it would bury the thing people came for. The count beside the
faces is the whole list's, not the strip's, so it never implies the server is
quieter than it is. */
export function OnlinePlayersPanel() {
  const presence = usePresenceStore((state) => state.presence);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const visible = useMemo(
    () => filterPlayers(presence.players, query),
    [presence.players, query],
  );

  if (presence.onlineCount === 0) return null;

  const faces = presence.players.slice(0, FACES_ON_THE_STRIP);
  const overflow = presence.onlineCount - faces.length;

  return (
    <>
      <button
        type="button"
        className="online-strip"
        data-testid="online-players-strip"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
      >
        <span className="online-strip-faces" aria-hidden="true">
          {faces.map((player) => (
            <Avatar
              key={player.userId}
              name={player.displayName}
              nameColor={player.nameColor ?? undefined}
              isAnonymous={player.isAnonymous}
              size={26}
            />
          ))}
          {overflow > 0 && <span className="online-strip-more">+{overflow}</span>}
        </span>
        <span className="online-strip-count">{presenceSummary(presence)}</span>
      </button>

      {open && (
        <BottomSheet
          title="Who is online"
          testId="online-players-sheet"
          onDismiss={() => {
            setOpen(false);
            setQuery("");
          }}
        >
          <div className="online-players-sheet">
            <div className="online-players-search">
              <SearchIcon size={16} />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter this list"
                aria-label="Filter the players shown"
              />
            </div>
            {presence.onlineCount > presence.players.length && (
              // Said out loud rather than left to be inferred: the field above
              // filters the rows on screen, and cannot find somebody the cap
              // left out. Answering "no such player" about somebody who is
              // online would be worse than not offering search at all.
              <p className="online-players-note">
                Showing the first {presence.players.length} of{" "}
                {presence.onlineCount} players online.
              </p>
            )}
            <ul className="online-players-list" data-testid="online-players-list">
              {visible.map((player) => (
                <li key={player.userId} className="online-player-row">
                  <Avatar
                    name={player.displayName}
                    nameColor={player.nameColor ?? undefined}
                    isAnonymous={player.isAnonymous}
                    size={30}
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
                  <StatusLabel status={player.status} />
                </li>
              ))}
            </ul>
            {visible.length === 0 && (
              <p className="online-players-empty">Nobody here matches that.</p>
            )}
          </div>
        </BottomSheet>
      )}
    </>
  );
}
