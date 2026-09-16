import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRoomEntry } from "../hooks/useRoomEntry";
import { describeDrawingRules } from "../lib/drawingRules";
import type { RoomSummary } from "../types";
import { AppHeader } from "./AppHeader";
import { AuthDialog } from "./AccountMenu";
import { EyeIcon, XIcon } from "./icons";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { MAX_NICKNAME_LENGTH } from "../lib/roomEntryState";
import { needsIdentity, useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

const INVITE_LOADING_DELAY_MS = 250;

function hintModeLabel(room: RoomSummary) {
  if (room.hideMaskedPrompt) return ui.inviteEntryPage.promptDetailsHidden;
  if (room.hintMode === "checkpoints") return ui.inviteEntryPage.timedHints;
  if (room.hintMode === "purchase") return ui.inviteEntryPage.buyableLetterHints;
  if (room.hintMode === "wheel") return ui.inviteEntryPage.wheelOfFortune;
  return ui.inviteEntryPage.noLetterHints;
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
  const { state, join, setNicknameInput } = useRoomEntry(code);
  const user = useAuthStore((store) => store.user);
  const hasResolved = useAuthStore((store) => store.hasResolved);
  const nameDraft = useAuthStore((store) => store.nameDraft);
  const setNameDraft = useAuthStore((store) => store.setNameDraft);
  const login = useAuthStore((store) => store.login);
  const register = useAuthStore((store) => store.register);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  // Nothing until the first GET /api/auth/me settles: a null user means "not
  // known yet" as well as "nobody", and a join in that window races the
  // provisioning request (see FirstRunIdentity).
  const asksForName = hasResolved && needsIdentity(user);
  const offersLogIn = hasResolved && (!user || user.isAnonymous);
  const room = state.status === "preview" || state.status === "joining" ? state.room : null;
  const busy = state.status === "joining";
  const entryError = state.status === "preview" ? state.error : undefined;
  const notice = state.status === "preview" || state.status === "joining" ? state.notice : undefined;

  return (
    <div className="invite-entry-page">
      <AppHeader backLabel={ui.inviteEntryPage.backLobby} />

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
              <p className="invite-eyebrow">{room.isPublic ? ui.inviteEntryPage.publicRoom : ui.inviteEntryPage.privateInvite} · {room.code}</p>
              <h1>{room.name}</h1>
            </div>
            <span className={`invite-state-badge ${room.state}`}>
              {room.state === "playing" ? ui.inviteEntryPage.inProgress : ui.inviteEntryPage.waiting}
            </span>
          </div>

          <p className="invite-room-headline">
            {ui.inviteEntryPage.hereCount({
              here: room.playerCount,
              capacity: room.maxPlayers,
              full: room.isFull,
            })}
          </p>

          {/* The room's rules, open. They used to fold on a phone because
              380px of them pushed Join off the bottom of the screen; the
              answer is docked now (#592), so they can take the room they
              want and the host who chose them is not second-guessed. */}
          <dl className="invite-room-facts">
            <div><dt>{ui.inviteEntryPage.players}</dt><dd>{room.playerCount}/{room.maxPlayers}{room.isFull ? ui.inviteEntryPage.full : ""}</dd></div>
            <div><dt>{ui.inviteEntryPage.rounds}</dt><dd>{room.rounds}</dd></div>
            <div><dt>{ui.inviteEntryPage.drawTime}</dt><dd>{room.drawingSeconds}s</dd></div>
            <div><dt>{ui.inviteEntryPage.scoring}</dt><dd>{room.scoringMode === "none" ? ui.inviteEntryPage.noScoring : room.scoringMode === "pressure" ? ui.inviteEntryPage.pressure : ui.inviteEntryPage.default}</dd></div>
          </dl>

          <ul className="invite-rule-list" aria-label={ui.inviteEntryPage.roomRules}>
            <li>{hintModeLabel(room)}</li>
            <li>{describeDrawingRules(room.allowedTools, room.colorMode) ?? ui.inviteEntryPage.everyToolAndColor}</li>
            <li>{room.spectatorsSeePrompt ? ui.inviteEntryPage.spectatorsCanSeeThePrompt : ui.inviteEntryPage.spectatorsGuessAlong}</li>
            <li>
              {room.customPromptCount > 0
                ? (room.customPromptsOnly
                  ? ui.inviteEntryPage.customPromptsOnly({ count: room.customPromptCount })
                  : ui.inviteEntryPage.customPromptsPlusDefaults({ count: room.customPromptCount }))
                : ui.inviteEntryPage.defaultPromptList}
            </li>
          </ul>

          {room.state === "playing" && (
            <p className="invite-callout">{ui.inviteEntryPage.thisGameAlreadyProgressJoiningAs}</p>
          )}
          {notice && <p className="invite-notice">{notice}</p>}

          {/* The answer: a name when one is needed, then Join or Spectate.
              One answer rather than two - the first-run block used to sit in
              here with a Play of its own, 90px above Join, and both saved the
              name. Docked to the bottom of the screen on a phone, so it is
              under the thumb from the first paint whatever the card above
              says; at the end of the card on a wider screen. A plain
              container, not a <form>: Enter in the field joins, and the
              account dialog brings its own form. */}
          <div className="invite-join-form">
            {asksForName && (
              <>
                {user?.nameInUse && (
                  <p className="invite-name-in-use" role="status">
                    {ui.firstRunIdentity.nameInUse({ name: user.displayName })}
                  </p>
                )}
                <label htmlFor="invite-name" className="visually-hidden">
                  {ui.firstRunIdentity.whatShouldWeCallYou}
                </label>
                {/* Search type suppresses Android Chrome's unrelated autofill
                    toolbar, matching every other name field in the app. */}
                <input
                  id="invite-name"
                  className="invite-name-input"
                  type="search"
                  inputMode="text"
                  value={nameDraft}
                  onChange={(event) => {
                    setNameDraft(event.target.value);
                    // Also to the entry machine, which drops a refusal about
                    // the name once the name changes; otherwise the error and
                    // aria-invalid stay up over a name that is now fine.
                    setNicknameInput(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !busy && !room.isFull) {
                      event.preventDefault();
                      void join("player");
                    }
                  }}
                  maxLength={MAX_NICKNAME_LENGTH}
                  placeholder={ui.firstRunIdentity.whatShouldWeCallYou}
                  autoComplete="nickname"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  enterKeyHint="go"
                  aria-invalid={entryError ? true : undefined}
                  aria-describedby={entryError ? "invite-entry-error" : undefined}
                />
              </>
            )}
            {entryError && <p id="invite-entry-error" className="invite-form-error" role="alert">{entryError}</p>}
            <div className="invite-actions">
              <button
                type="button"
                className="invite-primary-button"
                disabled={busy || room.isFull || !hasResolved}
                onClick={() => void join("player")}
              >
                {room.isFull ? ui.inviteEntryPage.roomFull : busy ? ui.inviteEntryPage.joining : room.state === "playing" ? ui.inviteEntryPage.joinGameInProgress : ui.inviteEntryPage.joinGame}
              </button>
              <button
                type="button"
                className={room.isFull ? "invite-primary-button" : "invite-secondary-button"}
                disabled={busy || !hasResolved}
                onClick={() => void join("spectator")}
              >
                <EyeIcon size={16} />
                {busy ? ui.inviteEntryPage.joining : ui.inviteEntryPage.spectate}
              </button>
            </div>
            {room.isFull && <p className="invite-action-hint">{ui.inviteEntryPage.playerSlotsAreFullSpectatingStill}</p>}
          </div>

          {/* Somebody who has an account on another device should arrive as
              it, not as a new guest. Under the answer rather than above it,
              where it read as a step to take first; on a phone the answer is
              docked, so this ends the card. Only that: creating an account is
              offered at the end of the first game, when there is something
              to keep. */}
          {offersLogIn && (
            <p className="invite-account-line">
              {ui.inviteEntryPage.haveAnAccount}{" "}
              <button type="button" className="invite-account-link" onClick={() => setAuthMode("login")}>
                {ui.firstRunIdentity.logIn}
              </button>
            </p>
          )}
          {authMode && (
            <AuthDialog
              mode={authMode}
              onClose={() => setAuthMode(null)}
              onSwitchMode={setAuthMode}
              onSubmit={authSubmitter(authMode, login, register)}
            />
          )}
        </main>
      )}
    </div>
  );
}
