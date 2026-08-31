import { promptLanguageLabel } from "../lib/promptLanguages";
import { ClockIcon, EyeIcon, Flag, RoundsIcon, UsersIcon } from "./icons";
import type { RoomSummary } from "../types";

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
          <span title="Players">
            <UsersIcon size={14} />
            {room.playerCount}/{room.maxPlayers}
          </span>
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
