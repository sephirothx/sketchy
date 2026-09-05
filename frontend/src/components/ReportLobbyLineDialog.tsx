import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import type { LobbyChatLine } from "../lib/lobbyChat";
import { submitPlayerReport, type ReportReason } from "../lib/moderation";
import { playerNameClass, playerNameStyle } from "../lib/playerName";

/** The reasons a line of chat can be reported for. A line is words, so the
reasons about a drawing, a picture, or play are left out rather than offered
and never true. */
const REASONS: { value: ReportReason; label: string }[] = [
  { value: "harassment", label: "Harassment or abuse" },
  { value: "spam", label: "Spam" },
  { value: "inappropriate_name", label: "Inappropriate name" },
];

/** What the report says when the reporter adds nothing. The server refuses a
blank, and the line itself is the complaint; a moderator opening the report
should read that rather than an empty box. */
const NO_DETAILS = "No details given - see the attached line.";

/** Report a line of the lobby's chat.

The room's dialog names a seat and lets the server pick the evidence. The
lobby has no seat - a line carries its author's account id for exactly this
reason (R-ROOM-07) - so this one goes over REST, names the account, and cites
the one line it was opened from. Nothing else is attached: the lobby is one
conversation rather than a room the server could gather from, and the line
is shown here so the reporter sees what they are citing. */
export function ReportLobbyLineDialog({
  line,
  retainedMessageId,
  onClose,
}: {
  line: LobbyChatLine;
  /** Held apart from the line so a caller cannot open this without one. */
  retainedMessageId: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const reasonRef = useRef<HTMLSelectElement | null>(null);
  const titleId = useId();
  const [reason, setReason] = useState<ReportReason>("harassment");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: reasonRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitPlayerReport({
        reportedUserId: line.userId,
        reason,
        details: details.trim() || NO_DETAILS,
        messageIds: [retainedMessageId],
      });
      setSent(true);
    } catch (problem) {
      setError(
        problem instanceof ApiError && problem.message
          ? problem.message
          : "That report could not be sent. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  // Portalled like the room's report dialog, and given its overlay class so it
  // sits on the same layer.
  return createPortal(
    <div
      className="modal-overlay report-player-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="report-lobby-line-dialog"
      >
        <h3 id={titleId} className="modal-title">
          {sent ? "Report sent" : `Report ${line.displayName}`}
        </h3>

        {!sent ? (
          <>
            <p className="modal-body">
              A moderator will see this line. Nothing happens to {line.displayName} right
              now, and they are not told who reported them.
            </p>
            <blockquote className="report-quoted-line" data-testid="report-quoted-line">
              <strong
                className={playerNameClass(line.isAnonymous)}
                style={playerNameStyle(line.nameColor ?? undefined, line.isAnonymous)}
              >
                {line.displayName}:{" "}
              </strong>
              {line.text}
            </blockquote>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-reason`}>What is wrong with it</label>
              <select
                id={`${titleId}-reason`}
                ref={reasonRef}
                className="settings-select"
                value={reason}
                onChange={(change) => setReason(change.target.value as ReportReason)}
              >
                {REASONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <label htmlFor={`${titleId}-details`}>Anything else (optional)</label>
              <textarea
                id={`${titleId}-details`}
                className="report-details"
                rows={3}
                maxLength={1000}
                value={details}
                onChange={(change) => {
                  setDetails(change.target.value);
                  setError(null);
                }}
                placeholder="Anything a moderator should know"
              />
              <p className="auth-hint">Only this line is attached.</p>

              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="modal-button" disabled={busy}>
                {busy ? "Sending…" : "Send report"}
              </button>
            </form>
          </>
        ) : (
          <>
            <p className="modal-body">Sent, with the line attached.</p>
            <button type="button" className="modal-button" onClick={onClose}>
              Done
            </button>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sent ? "Close" : "Cancel"}
        </button>
      </div>
    </div>,
    document.body,
  );
}
