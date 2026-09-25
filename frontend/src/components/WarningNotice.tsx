import { useClock } from "../hooks/useClock";
import { useEffect, useRef, useState } from "react";

import {
  acknowledgeWarning,
  fetchPendingWarning,
  fetchWarningDrawing,
  reportedDrawing,
  type PendingWarning,
} from "../lib/moderation";
import { asReportReason, humanizeCategory } from "../lib/moderation";
import { ruleAnchorFor } from "../content/rules/anchors.ts";
import { socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { ReportedDrawing } from "./ReportedDrawing";
import { ModalShell } from "./ui/ModalShell";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";

/** Keep only a payload shaped like a warning; a malformed one is dropped
rather than rendered as "undefined" in front of the player. */
function warningFromPayload(payload: unknown): PendingWarning | null {
  if (!payload || typeof payload !== "object") return null;
  const body = (payload as { warning?: unknown }).warning;
  if (!body || typeof body !== "object") return null;
  const warning = body as Record<string, unknown>;
  if (typeof warning.id !== "string" || typeof warning.reason !== "string") {
    return null;
  }
  return {
    id: warning.id,
    kind: warning.kind === "avatar_removal" ? "avatar_removal" : "warning",
    reason: warning.reason,
    category: asReportReason(warning.category),
    createdAt: typeof warning.createdAt === "string" ? warning.createdAt : "",
    messages: Array.isArray(warning.messages)
      ? warning.messages.filter(
          (line): line is { text: string; at: string | null } =>
            !!line && typeof (line as { text?: unknown }).text === "string",
        )
      : [],
    drawings: Array.isArray(warning.drawings)
      ? warning.drawings.flatMap((entry) => {
          const drawing = reportedDrawing(entry);
          const reportId = (entry as { reportId?: unknown })?.reportId;
          return drawing && typeof reportId === "string"
            ? [{ ...drawing, reportId }]
            : [];
        })
      : [],
  };
}

/** Show a moderator's warning to its player, once.

The step between a report going nowhere and an account being suspended:
nothing is restricted, but the player is told what was reported - in their own
words - and that a moderator looked. Acknowledging it records that the message
actually landed, and it does not come back. */
export function WarningNotice() {
  const { dateTime } = useClock();
  const userId = useAuthStore((state) => state.user?.id);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [warning, setWarning] = useState<PendingWarning | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const acknowledgeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!hasResolved || !userId) return;
    let cancelled = false;
    void fetchPendingWarning()
      .then((result) => {
        if (!cancelled) setWarning(result.warning);
      })
      .catch(() => {
        // Nothing to do: the warning stays pending server-side and will be
        // fetched again on the next visit.
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, userId]);

  useEffect(() => {
    // A player who is online when the moderator decides hears it now; the
    // fetch above is the catch-up route for everybody else.
    function onModeratorWarning(payload: unknown) {
      const pushed = warningFromPayload(payload);
      if (pushed) {
        setWarning(pushed);
        setFailed(false);
      }
    }
    socket.on("moderator_warning", onModeratorWarning);
    return () => {
      socket.off("moderator_warning", onModeratorWarning);
    };
  }, []);

  if (!warning) return null;

  // A removal restricts something; a formal warning restricts nothing. They
  // share this surface and must not share its words.
  const isRemoval = warning.kind === "avatar_removal";

  async function dismiss() {
    if (busy || !warning) return;
    setBusy(true);
    setFailed(false);
    try {
      await acknowledgeWarning(warning.id);
      setWarning(null);
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
      <p className="modal-body suspension-reason">{warning.reason}</p>
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
            <ReportedDrawing
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
