import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRoomEntry } from "../hooks/useRoomEntry";
import { useSettingsStore } from "../store/settingsStore";
import type { RoomSummary } from "../types";
import { SettingsIcon } from "./SettingsIcon";
import { AccountMenu } from "./AccountMenu";
import { FirstRunIdentity } from "./FirstRunIdentity";

const INVITE_LOADING_DELAY_MS = 250;

function hintModeLabel(room: RoomSummary) {
  if (room.hideMaskedPrompt) return "Prompt details hidden";
  if (room.hintMode === "checkpoints") return "Timed letter hints";
  if (room.hintMode === "purchase") return "Buyable letter hints";
  if (room.hintMode === "wheel") return "Wheel-style letter hints";
  return "No letter hints";
}

function DelayedInviteLoader() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => setVisible(true), INVITE_LOADING_DELAY_MS);
    return () => window.clearTimeout(timeout);
  }, []);

  if (!visible) return null;
  return (
    <main className="invite-card invite-loading-card" aria-live="polite">
      <div className="invite-loading-spinner" aria-hidden="true" />
      <h1>Checking your invite…</h1>
      <p>Loading room details.</p>
    </main>
  );
}

export function InviteEntryPage({ code }: { code: string }) {
  const navigate = useNavigate();
  const openSettings = useSettingsStore((state) => state.openSettings);
  const { state, join } = useRoomEntry(code);
  const room = state.status === "preview" || state.status === "joining" ? state.room : null;
  const busy = state.status === "joining";
  const entryError = state.status === "preview" ? state.error : undefined;
  const notice = state.status === "preview" || state.status === "joining" ? state.notice : undefined;

  return (
    <div className="invite-entry-page">
      <header className="invite-entry-header">
        <button type="button" className="invite-brand" onClick={() => navigate("/")}>Sketchy</button>
        <div className="lobby-header-actions">
          <AccountMenu />
          <button type="button" className="header-settings-button" onClick={openSettings} title="Game Settings">
            <SettingsIcon size={16} />
            <span>Settings</span>
          </button>
        </div>
      </header>

      {state.status === "error" ? (
        <main className="invite-card invite-unavailable-card">
          <div className="invite-status-icon" aria-hidden="true">✕</div>
          <p className="invite-eyebrow">Room {code}</p>
          <h1>Room unavailable</h1>
          <p>{state.message}</p>
          <button type="button" className="invite-primary-button" onClick={() => navigate("/")}>Back to lobby</button>
        </main>
      ) : !room ? (
        <DelayedInviteLoader />
      ) : (
        <main className="invite-card">
          <div className="invite-card-heading">
            <div>
              <p className="invite-eyebrow">{room.isPublic ? "Public room" : "Private invite"} · {room.code}</p>
              <h1>{room.name}</h1>
            </div>
            <span className={`invite-state-badge ${room.state}`}>
              {room.state === "playing" ? "In progress" : "Waiting"}
            </span>
          </div>

          <dl className="invite-room-facts">
            <div><dt>Players</dt><dd>{room.playerCount}/{room.maxPlayers}{room.isFull ? " · Full" : ""}</dd></div>
            <div><dt>Rounds</dt><dd>{room.rounds}</dd></div>
            <div><dt>Draw time</dt><dd>{room.drawingSeconds}s</dd></div>
            <div><dt>Scoring</dt><dd>{room.scoringMode === "none" ? "Just for fun" : "Points on"}</dd></div>
          </dl>

          <ul className="invite-rule-list" aria-label="Room rules">
            <li>{hintModeLabel(room)}</li>
            <li>{room.spectatorsSeeSolution ? "Spectators can see the answer" : "Spectators guess along"}</li>
            <li>
              {room.customWordCount > 0
                ? `${room.customWordCount} custom words${room.customWordsOnly ? " only" : " plus defaults"}`
                : "Default word list"}
            </li>
          </ul>

          {room.state === "playing" && (
            <p className="invite-callout">This game is already in progress. Joining as a player adds you to a future turn.</p>
          )}
          {notice && <p className="invite-notice">{notice}</p>}

          <form
            className="invite-join-form"
            autoComplete="off"
            onSubmit={(event) => {
              event.preventDefault();
              if (!room.isFull) void join("player");
            }}
          >
            {/* Cold arrivals from an invite link need an identity before they
                can join. Same block as the lobby: account first, guest name
                inline underneath. It disappears once either exists. */}
            <FirstRunIdentity compact />
            {entryError && <p id="invite-entry-error" className="invite-form-error" role="alert">{entryError}</p>}
            <div className="invite-actions">
              <button type="submit" className="invite-primary-button" disabled={busy || room.isFull}>
                {room.isFull ? "Room full" : busy ? "Joining…" : room.state === "playing" ? "Join game in progress" : "Join game"}
              </button>
              <button
                type="button"
                className={room.isFull ? "invite-primary-button" : "invite-secondary-button"}
                disabled={busy}
                onClick={() => void join("spectator")}
              >
                {busy ? "Joining…" : "Spectate"}
              </button>
            </div>
            {room.isFull && <p className="invite-action-hint">Player slots are full. Spectating is still open.</p>}
          </form>
        </main>
      )}
    </div>
  );
}
