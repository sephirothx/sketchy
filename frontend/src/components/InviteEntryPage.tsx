import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useRoomEntry } from "../hooks/useRoomEntry";
import { describeDrawingRules } from "../lib/drawingRules";
import type { RoomSummary } from "../types";
import { AppHeader } from "./AppHeader";
import { FirstRunIdentity } from "./FirstRunIdentity";
import { XIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

const INVITE_LOADING_DELAY_MS = 250;

function hintModeLabel(room: RoomSummary) {
  if (room.hideMaskedPrompt) return "Prompt details hidden";
  if (room.hintMode === "checkpoints") return "Timed hints";
  if (room.hintMode === "purchase") return "Buyable letter hints";
  if (room.hintMode === "wheel") return "Wheel of Fortune";
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
      <h1>{ui.inviteEntryPage.checkingYourInvite}</h1>
      <p>{ui.inviteEntryPage.loadingRoomDetails}</p>
    </main>
  );
}

export function InviteEntryPage({ code }: { code: string }) {
  const navigate = useNavigate();
  const isMobile = useMediaQuery("(max-width: 900px)");
  const { state, join } = useRoomEntry(code);
  const room = state.status === "preview" || state.status === "joining" ? state.room : null;
  const busy = state.status === "joining";
  const entryError = state.status === "preview" ? state.error : undefined;
  const notice = state.status === "preview" || state.status === "joining" ? state.notice : undefined;

  return (
    <div className="invite-entry-page">
      <AppHeader backLabel="Back to lobby" />

      {state.status === "error" ? (
        <main className="invite-card invite-unavailable-card">
          <div className="invite-status-icon" aria-hidden="true"><XIcon size={20} /></div>
          <p className="invite-eyebrow">{ui.inviteEntryPage.roomCode({ code })}</p>
          <h1>{ui.inviteEntryPage.roomUnavailable}</h1>
          <p>{state.message}</p>
          <button type="button" className="invite-primary-button" onClick={() => navigate("/")}>{ui.inviteEntryPage.backLobby}</button>
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

          <p className="invite-room-headline">
            {ui.inviteEntryPage.hereCount({
              here: room.playerCount,
              capacity: room.maxPlayers,
              full: room.isFull,
            })}
          </p>

          {/* The settings matter to the host who chose them, and to nobody
              tapping a friend's link. Open by default on a wide screen, where
              there is room for them; folded on a phone, where 380px of them
              pushed the Join button off the bottom of the screen. */}
          <details className="invite-details" open={!isMobile}>
            <summary>
              <span className="invite-details-summary">
                {ui.inviteEntryPage.roomSummary({
                  rounds: room.rounds,
                  seconds: room.drawingSeconds,
                  hintMode: hintModeLabel(room).toLowerCase(),
                })}
              </span>
            </summary>
            <dl className="invite-room-facts">
              <div><dt>{ui.inviteEntryPage.players}</dt><dd>{room.playerCount}/{room.maxPlayers}{room.isFull ? " · Full" : ""}</dd></div>
              <div><dt>{ui.inviteEntryPage.rounds}</dt><dd>{room.rounds}</dd></div>
              <div><dt>{ui.inviteEntryPage.drawTime}</dt><dd>{room.drawingSeconds}s</dd></div>
              <div><dt>{ui.inviteEntryPage.scoring}</dt><dd>{room.scoringMode === "none" ? "No scoring" : room.scoringMode === "pressure" ? "Pressure" : "Default"}</dd></div>
            </dl>

            <ul className="invite-rule-list" aria-label={ui.inviteEntryPage.roomRules}>
              <li>{hintModeLabel(room)}</li>
              <li>{describeDrawingRules(room.allowedTools, room.colorMode) ?? "Every tool and color"}</li>
              <li>{room.spectatorsSeePrompt ? "Spectators can see the prompt" : "Spectators guess along"}</li>
              <li>
                {room.customPromptCount > 0
                  ? `${room.customPromptCount} custom prompts${room.customPromptsOnly ? " only" : " plus defaults"}`
                  : "Default prompt list"}
              </li>
            </ul>
          </details>

          {room.state === "playing" && (
            <p className="invite-callout">{ui.inviteEntryPage.thisGameAlreadyProgressJoiningAs}</p>
          )}
          {notice && <p className="invite-notice">{notice}</p>}

          {/* A plain container, not a <form>: this block has no fields of its
              own any more, and the identity block below brings its own forms
              for the guest name and the account dialog. Nesting those inside a
              form is invalid HTML - React leaves the inner onSubmit unwired, so
              the browser submits natively and reloads the invite page instead. */}
          <div className="invite-join-form">
            {/* Cold arrivals from an invite link need an identity before they
                can join. Same block as the lobby: account first, guest name
                inline underneath. It disappears once either exists. */}
            <FirstRunIdentity compact />
            {entryError && <p id="invite-entry-error" className="invite-form-error" role="alert">{entryError}</p>}
            <div className="invite-actions">
              <button
                type="button"
                className="invite-primary-button"
                disabled={busy || room.isFull}
                onClick={() => void join("player")}
              >
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
            {room.isFull && <p className="invite-action-hint">{ui.inviteEntryPage.playerSlotsAreFullSpectatingStill}</p>}
          </div>
        </main>
      )}
    </div>
  );
}
