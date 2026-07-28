import type { RoomSummary } from "../types";

interface PublicRoomCardProps {
  room: RoomSummary;
  busy: boolean;
  pendingMode: "join" | "spectate" | null;
  onJoin: (asSpectator: boolean) => void;
}

function exceptionalRules(room: RoomSummary) {
  const rules: string[] = [];
  if (room.scoringMode === "none") rules.push("No scoring");
  if (room.hideMaskedPrompt) rules.push("Hidden prompt");
  if (room.customWordCount > 0) {
    rules.push(room.customWordsOnly ? "Custom words only" : `${room.customWordCount} custom words`);
  }
  if (room.hintMode !== "none") {
    rules.push(room.hintMode === "checkpoints" ? "Timed hints" : room.hintMode === "wheel" ? "Buy-a-letter hints" : "Buyable hints");
  }
  if (room.spectatorsSeeSolution) rules.push("Spectators see word");
  return rules;
}

function hintDescription(room: RoomSummary) {
  if (room.hideMaskedPrompt) return "Prompt details are hidden and hints are off";
  if (room.hintMode === "checkpoints") return "Timed letter hints";
  if (room.hintMode === "purchase") return "Players can buy letter hints";
  if (room.hintMode === "wheel") return "Players can buy full letters";
  return "No letter hints";
}

export function PublicRoomCard({ room, busy, pendingMode, onJoin }: PublicRoomCardProps) {
  const full = room.isFull || room.playerCount >= room.maxPlayers;
  const primaryLabel = full ? "Spectate" : room.state === "playing" ? "Join in progress" : "Join";
  const badges = exceptionalRules(room);

  return (
    <article className="public-room-card" data-testid="public-room-card">
      <div className="public-room-card-main">
        <div className="public-room-title-row">
          <h3>{room.name}</h3>
          <span className={`room-state-badge room-state-${room.state}`}>
            {room.state === "playing" ? "In progress" : "Waiting"}
          </span>
        </div>
        <p className="public-room-facts">
          <span>{room.playerCount}/{room.maxPlayers} players</span>
          <span>{room.rounds} {room.rounds === 1 ? "round" : "rounds"}</span>
          <span>{room.drawingSeconds}s draws</span>
          {room.spectatorCount > 0 && <span>{room.spectatorCount} spectating</span>}
          {full && <strong>Full</strong>}
        </p>
        {badges.length > 0 && <div className="public-room-badges">{badges.map((badge) => <span key={badge}>{badge}</span>)}</div>}
        <details className="public-room-rules">
          <summary>View rules</summary>
          <ul>
            <li>{room.scoringMode === "default" ? "Default scoring" : "No scorekeeping"}</li>
            <li>{hintDescription(room)}</li>
            <li>{room.customWordCount > 0 ? (room.customWordsOnly ? `${room.customWordCount} custom words only` : `${room.customWordCount} custom words plus the default list`) : "Built-in word list"}</li>
            <li>{room.spectatorsSeeSolution ? "Spectators can see the solution" : "Spectators see the masked prompt"}</li>
          </ul>
        </details>
      </div>
      <div className="public-room-actions">
        <button type="button" className="public-room-primary-action" disabled={busy} onClick={() => onJoin(full)}>{pendingMode === (full ? "spectate" : "join") ? (full ? "Joining as spectator…" : "Joining…") : primaryLabel}</button>
        {!full && <button type="button" className="public-room-secondary-action" disabled={busy} onClick={() => onJoin(true)}>{pendingMode === "spectate" ? "Joining as spectator…" : "Spectate"}</button>}
      </div>
    </article>
  );
}
