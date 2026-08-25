import { describeDrawingRules } from "../lib/drawingRules";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { Chip } from "./ui/Chip";
import { ClockIcon, EyeIcon, Flag, RoundsIcon, UsersIcon } from "./icons";
import type { RoomSummary } from "../types";

interface PublicRoomCardProps {
  room: RoomSummary;
  busy: boolean;
  pendingMode: "join" | "spectate" | null;
  onJoin: (asSpectator: boolean) => void;
}

/* The tag chips carry every rule that differs from the defaults, so a card
   needs no expandable settings list. */
function exceptionalRules(room: RoomSummary) {
  const rules: string[] = [];
  if (room.scoringMode === "none") rules.push("No scoring");
  if (room.scoringMode === "pressure") rules.push("Pressure");
  if (room.hideMaskedPrompt) rules.push("Hidden prompt");
  if (room.customPromptCount > 0) {
    rules.push(room.customPromptsOnly ? "Custom prompts only" : `${room.customPromptCount} custom prompts`);
  }
  if (room.hintMode !== "none") {
    rules.push(room.hintMode === "checkpoints" ? "Timed hints" : room.hintMode === "wheel" ? "Wheel of Fortune" : "Buy letters");
  }
  if (room.spectatorsSeePrompt) rules.push("Spectators see prompt");
  const drawingRules = describeDrawingRules(room.allowedTools, room.colorMode);
  if (drawingRules) rules.push(drawingRules);
  return rules;
}

export function PublicRoomCard({ room, busy, pendingMode, onJoin }: PublicRoomCardProps) {
  const full = room.isFull || room.playerCount >= room.maxPlayers;
  const primaryLabel = room.state === "playing" ? "Join in progress" : "Join";
  const tags = exceptionalRules(room);
  const languageLabel = promptLanguageLabel(room.promptLanguage);
  const fillFraction = room.maxPlayers > 0 ? room.playerCount / room.maxPlayers : 0;

  return (
    <article className="public-room-card" data-testid="public-room-card">
      <div className="public-room-card-main">
        <div className="public-room-title-row">
          <h3>{room.name}</h3>
          <Chip
            kind={room.state === "playing" ? "warning" : "success"}
            className={`room-state-badge room-state-${room.state}`}
          >
            {room.state === "playing" ? "In progress" : "Waiting"}
          </Chip>
        </div>
        <p className="public-room-facts">
          <span title={`Prompt language: ${languageLabel}`}>
            <Flag language={room.promptLanguage} />
            {languageLabel}
          </span>
          <span title="Players">
            <UsersIcon size={14} />
            {room.playerCount}/{room.maxPlayers}
            <span className="public-room-capacity" aria-hidden="true">
              <span
                className={full ? "is-full" : undefined}
                style={{ width: `${Math.round(Math.min(1, fillFraction) * 100)}%` }}
              />
            </span>
          </span>
          <span title="Rounds">
            <RoundsIcon size={14} />
            {room.rounds} {room.rounds === 1 ? "round" : "rounds"}
          </span>
          <span title="Drawing time">
            <ClockIcon size={14} />
            {room.drawingSeconds}s
          </span>
          {room.spectatorCount > 0 && (
            <span title="Spectators">
              <EyeIcon size={14} />
              {room.spectatorCount}
            </span>
          )}
          {full && <strong>Full</strong>}
        </p>
        {tags.length > 0 && (
          <div className="public-room-badges">
            {tags.map((tag) => (
              <Chip key={tag}>{tag}</Chip>
            ))}
          </div>
        )}
      </div>
      <div className="public-room-actions">
        {!full && (
          <button
            type="button"
            className={`btn ${room.state === "playing" ? "btn-warm" : "btn-primary"} public-room-primary-action`}
            disabled={busy}
            onClick={() => onJoin(false)}
          >
            {pendingMode === "join" ? "Joining…" : primaryLabel}
          </button>
        )}
        <button
          type="button"
          className="btn btn-secondary public-room-secondary-action"
          disabled={busy}
          onClick={() => onJoin(true)}
        >
          <EyeIcon size={14} />
          {pendingMode === "spectate" ? "Joining as spectator…" : "Spectate"}
        </button>
      </div>
    </article>
  );
}
