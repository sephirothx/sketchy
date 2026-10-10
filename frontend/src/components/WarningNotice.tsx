import { useClock } from "../hooks/useClock";
import { useEffect, useRef, useState } from "react";

import { acknowledgeWarning, fetchWarningDrawing } from "../lib/moderation";
import { humanizeCategory } from "../lib/moderation";
import { onSuspended } from "../lib/suspension";
import { ruleAnchorFor } from "../content/rules/anchors.ts";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { useInboxStore } from "../store/inboxStore";
import { ModalShell } from "./ui/ModalShell";
import { LazyReportedDrawing } from "./LazyReportedDrawing";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";

/** A moderator's warning, which the player must acknowledge before going on.

The step between a report going nowhere and an account being suspended:
nothing is restricted, but the player is told what was reported - in their own
words - and that a moderator looked. Until it is acknowledged the account
cannot take a seat (R-INBOX-04): the server refuses, so another tab cannot
skip it. Answered once, it stays in the inbox as what happened (#1436).

It is read from the inbox, which every push and every connection reads again,
so it reaches a tab that was offline when it was issued. It never opens over a
game: a warning issued mid-turn waits for the waiting room, the lobby or any
other page, because a dialog in front of a turn is the one thing the inbox is
built not to do (R-INBOX-02). And never over a suspension, which says more and
ends the session anyway: one dialog at a time, the more serious first. */
export function WarningNotice() {
  const { dateTime, date } = useClock();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const pending = useInboxStore((state) => state.mustAcknowledge);
  const owner = useInboxStore((state) => state.owner);
  const playing = useGameStore((state) => state.roomId !== null && state.roomState === "playing");
  const [suspended, setSuspended] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const acknowledgeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => onSuspended(() => setSuspended(true)), []);

  const warning = owner !== null && owner === userId ? pending : null;
  if (!warning || playing || suspended) return null;

  // A removal restricts something; a formal warning restricts nothing. They
  // share this surface and must not share its words.
  const isRemoval = warning.kind === "avatar_removal";

  async function dismiss() {
    if (busy || !warning || userId === null) return;
    setBusy(true);
    setFailed(false);
    try {
      await acknowledgeWarning(warning.id);
      // The next one, if two were waiting, comes from this read.
      await useInboxStore.getState().refresh(userId);
    } catch {
      // Leave the notice up: closing it without the receipt landing would
      // mark nothing. Said, so the button that did nothing is not a mystery,
      // and pressing it again is the way on.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  // Answered, never dismissed: acknowledging is what records that it landed,
  // so there is no ✕, no Escape and no scrim to close it without that.
  return (
    <ModalShell
      role="alertdialog"
      title={isRemoval ? ui.warningNotice.yourPictureWasRemoved : ui.warningNotice.aModeratorWarning}
      overlayClassName="suspension-overlay"
      cardClassName="suspension-card"
      initialFocusRef={acknowledgeRef}
      footer={
        <button
          ref={acknowledgeRef}
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => void dismiss()}
        >
          {busy ? ui.warningNotice.oneMoment : ui.warningNotice.understood}
        </button>
      }
    >
      {warning.category && (
        <p className="modal-body notice-category" data-testid="warning-category">
          {/* The rule itself, not just its name: a decision you can read
              the rule behind is one you can check rather than only be
              told (R-RULES-02). */}
          {fill(ui.moderationNotice.recordedAs, {
            category: (
              <a href={ruleAnchorFor(warning.category)}>
                {humanizeCategory(warning.category)}
              </a>
            ),
          })}
        </p>
      )}
      {isRemoval ? (
        <p className="modal-body suspension-reason">
          {warning.uploadAgainAt
            ? ui.warningNotice.uploadAgainOn({ date: date(new Date(warning.uploadAgainAt)) })
            : ui.warningNotice.uploadAgainNow}
        </p>
      ) : (
        <p className="modal-body suspension-reason">{warning.reason}</p>
      )}
      {/* A removal shares this surface and nothing else. Saying "nothing is
          restricted" of one would be false - it restricts uploading, and by
          more each time (R-AVA-08) - so a removal says what it restricts,
          which its own words above already carry, and stops there. */}
      <p className="modal-body">
        {isRemoval ? (
          ui.warningNotice.aReportAboutYourPicture
        ) : (
          <>
            {/* What a warning is *for* - the step between nothing and a
                suspension - said in general terms. Naming a ladder would
                promise one nobody is bound to and nothing enforces. */}
            {ui.warningNotice.whatAWarningMeans}
          </>
        )}
      </p>
      {warning.messages.length > 0 && (
        <>
          <p className="modal-body suspension-evidence-label">
            {warning.messages.length === 1
              ? ui.moderationNotice.theMessageThisWasAbout
              : ui.moderationNotice.theMessagesThisWasAbout}
          </p>
          {/* Reuses the suspension notice's evidence styling: both lists
              are "your own words, as reported". */}
          <ul className="suspension-evidence">
            {warning.messages.map((message, index) => (
              <li key={`${message.at ?? index}-${index}`}>
                {message.at && (
                  <span className="suspension-evidence-time">
                    {dateTime(new Date(message.at))}
                  </span>
                )}
                <span className="suspension-evidence-text">{message.text}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {warning.drawings.length > 0 && (
        <>
          <p className="modal-body suspension-evidence-label">
            {warning.drawings.length === 1
              ? ui.moderationNotice.theDrawingThisWasAbout
              : ui.moderationNotice.theDrawingsThisWasAbout}
          </p>
          {warning.drawings.map((drawing) => (
            <LazyReportedDrawing
              key={drawing.reportId}
              className="suspension-drawing"
              load={() => fetchWarningDrawing(warning.id, drawing.reportId)}
              label={ui.moderationNotice.yourReportedDrawing({ prompt: drawing.prompt })}
              caption={<>{ui.moderationNotice.youWereAskedDraw} <strong>{drawing.prompt}</strong>.</>}
            />
          ))}
        </>
      )}
      {failed && (
        <p className="auth-error" role="alert">
          {ui.dialog.couldNotSave}
        </p>
      )}
    </ModalShell>
  );
}
