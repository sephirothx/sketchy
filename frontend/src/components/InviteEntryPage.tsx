import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRoomEntry } from "../hooks/useRoomEntry";
import { MAX_NICKNAME_LENGTH } from "../lib/roomEntryState";
import { useSettingsStore } from "../store/settingsStore";
import type { RoomSummary } from "../types";
import { SettingsIcon } from "./SettingsIcon";

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
  const { state, nicknameInput, setNicknameInput, join, isRegistered, username } = useRoomEntry(code);
  const room = state.status === "preview" || state.status === "joining" ? state.room : null;
  const busy = state.status === "joining";
  const entryError = state.status === "preview" ? state.error : undefined;
  const notice = state.status === "preview" || state.status === "joining" ? state.notice : undefined;

  return (
    <div className="invite-page">
      <div className="invite-header-actions">
        <button
          type="button"
          className="header-settings-button"
          onClick={openSettings}
          title="Game Settings"
          aria-label="Game Settings"
        >
          <SettingsIcon size={16} />
          <span>Settings</span>
        </button>
      </div>

      <DelayedInviteLoader />

      {state.status === "error" && (
        <main className="invite-card invite-error-card" role="alert">
          <h1>Unable to join room</h1>
          <p>{state.message}</p>
          <button type="button" className="invite-secondary-button" onClick={() => navigate("/")}>
            Back to lobby
          </button>
        </main>
      )}

      {room && (
        <main className="invite-card">
          <div className="invite-pill-row">
            <span className="invite-pill">{room.isPublic ? "Public room" : "Private invite"}</span>
            <span className="invite-pill">{room.playerCount}/{room.maxPlayers}</span>
            <span className="invite-pill">{hintModeLabel(room)}</span>
          </div>

          <h1>{room.name}</h1>
          <p className="invite-subtitle">
            {room.isFull ? "This room is full for active players, but you can still join as a spectator." : "You've been invited to play Sketchy."}
          </p>

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
            {isRegistered ? (
              <div style={{ marginBottom: "1rem" }}>
                <span style={{ fontWeight: 600, fontSize: "14px", color: "var(--color-text-secondary, #64748b)" }}>
                  Playing as
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "4px" }}>
                  <span style={{ fontWeight: 700, fontSize: "16px" }}>{username}</span>
                  <span style={{ fontSize: "12px", color: "var(--color-text-muted, #94a3b8)" }}>(Registered username)</span>
                </div>
              </div>
            ) : (
              <>
                <label htmlFor="invite-nickname">Your nickname</label>
                {/* Search type + autocomplete=off suppress Android Chrome's unrelated autofill toolbar. */}
                <input
                  id="invite-nickname"
                  name="sketchy-invite-name"
                  type="search"
                  inputMode="text"
                  value={nicknameInput}
                  onChange={(event) => setNicknameInput(event.target.value)}
                  maxLength={MAX_NICKNAME_LENGTH}
                  placeholder="Your name"
                  autoComplete="off"
                  autoCapitalize="words"
                  spellCheck={false}
                  autoCorrect="off"
                  enterKeyHint="go"
                  autoFocus
                  disabled={busy}
                  aria-describedby={entryError ? "invite-entry-error" : undefined}
                />
              </>
            )}
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
