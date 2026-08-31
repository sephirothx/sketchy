import { useState } from "react";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { emitWithAck } from "../lib/socket";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { Avatar } from "./ui/Avatar";
import { ChevronDownIcon, ClockIcon, EyeIcon, Flag, RoundsIcon, UsersIcon } from "./icons";
import type { RoomSummary } from "../types";

interface RosterEntry {
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
  isHost?: boolean;
}

interface PublicRoomCardProps {
  room: RoomSummary;
  busy: boolean;
  pendingMode: "join" | "spectate" | null;
  onJoin: (asSpectator: boolean) => void;
}

/**
 * One open room, as a row you can scan in a second.
 *
 * The facts are the ones that decide whether to tap: what it is called, what
 * language the prompts are in, how full it is, and how long a game will take
 * (rounds x drawing time). Everything else the card used to carry — a chip per
 * house rule, a capacity meter, the spectator count — priced the room rather
 * than described it, and on a phone it pushed the next room off the screen.
 * The room's own settings are one tap away on the other side of Join.
 */
export function PublicRoomCard({ room, busy, pendingMode, onJoin }: PublicRoomCardProps) {
  const full = room.isFull || room.playerCount >= room.maxPlayers;
  const playing = room.state === "playing";
  const languageLabel = promptLanguageLabel(room.promptLanguage);

  // Who is in there is fetched for this room when it is asked for, never
  // carried by the room list - see Room.to_public_roster.
  const [roster, setRoster] = useState<RosterEntry[] | null>(null);
  const [rosterOpen, setRosterOpen] = useState(false);
  const [rosterError, setRosterError] = useState<string | null>(null);

  async function toggleRoster() {
    if (rosterOpen) {
      setRosterOpen(false);
      return;
    }
    setRosterOpen(true);
    setRosterError(null);
    try {
      const ack = await emitWithAck<{ ok: boolean; players?: RosterEntry[] }>(
        "get_room_preview",
        { code: room.code },
      );
      if (ack?.ok && Array.isArray(ack.players)) {
        setRoster(ack.players);
      } else {
        setRosterError("Could not read who is in this room.");
      }
    } catch {
      setRosterError("Could not read who is in this room.");
    }
  }

  return (
    <article className="public-room-card" data-testid="public-room-card">
      <div className="public-room-card-main">
        {/* The flag rides on the name's line: it is part of what the room is
            rather than one of the numbers describing it, and it buys the
            facts row back a slot. The language's name is read out rather than
            printed, for anyone who cannot see the flag or is unsure of it. */}
        <h3 className="public-room-name">
          <span className="public-room-name-text">{room.name}</span>
          <span className="public-room-language" title={`Prompt language: ${languageLabel}`}>
            <Flag language={room.promptLanguage} />
            <span className="visually-hidden">{languageLabel}</span>
          </span>
        </h3>
        <p className="public-room-facts">
          {/* The count is the control: tapping it is how you find out who
              those players are. */}
          <button
            type="button"
            className={`public-room-roster-toggle${rosterOpen ? " is-open" : ""}`}
            aria-expanded={rosterOpen}
            onClick={() => void toggleRoster()}
            title="See who is in this room"
          >
            <UsersIcon size={14} />
            {room.playerCount}/{room.maxPlayers}
            <ChevronDownIcon size={12} />
          </button>
          <span title="Rounds">
            <RoundsIcon size={14} />
            {room.rounds} {room.rounds === 1 ? "round" : "rounds"}
          </span>
          <span title="Drawing time">
            <ClockIcon size={14} />
            {room.drawingSeconds}s
          </span>
          {/* Not decoration: full removes the Join button, and a game already
              running means joining puts you in a later turn. */}
          {full && <strong className="public-room-flag">Full</strong>}
          {!full && playing && <strong className="public-room-flag is-playing">In progress</strong>}
        </p>
        {rosterOpen && (
          <div className="public-room-roster">
            {rosterError && <p className="public-room-roster-note" role="alert">{rosterError}</p>}
            {!rosterError && roster === null && (
              <p className="public-room-roster-note">Looking…</p>
            )}
            {!rosterError && roster !== null && roster.length === 0 && (
              <p className="public-room-roster-note">Nobody is seated yet.</p>
            )}
            {!rosterError && roster !== null && roster.length > 0 && (
              <ul>
                {roster.map((player, index) => (
                  <li key={`${player.nickname}-${index}`}>
                    <Avatar
                      name={player.nickname}
                      nameColor={player.nameColor}
                      isAnonymous={player.isAnonymous}
                      size={22}
                    />
                    <span
                      className={playerNameClass(player.isAnonymous)}
                      style={playerNameStyle(player.nameColor, player.isAnonymous)}
                    >
                      {player.nickname}
                    </span>
                    {player.isHost && <span className="public-room-roster-host">host</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <div className="public-room-actions">
        {!full && (
          <button
            type="button"
            className={`btn ${playing ? "btn-warm" : "btn-primary"} public-room-primary-action`}
            disabled={busy}
            onClick={() => onJoin(false)}
          >
            {pendingMode === "join" ? "Joining…" : "Join"}
          </button>
        )}
        <button
          type="button"
          className="btn btn-secondary public-room-secondary-action"
          disabled={busy}
          onClick={() => onJoin(true)}
        >
          <EyeIcon size={14} />
          {pendingMode === "spectate" ? "Joining…" : "Spectate"}
        </button>
      </div>
    </article>
  );
}
