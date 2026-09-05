import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { reportPlayerInRoom, type ReportReason } from "../lib/moderation";
import { socketRequestErrorMessage } from "../lib/socket";

/** What went with the report, in one sentence.

Each part is stated from the acknowledgement rather than from what was asked
for: the turn can end between opening the dialog and sending, and a reporter
who ticked the box should hear that the drawing did not make it. */
function sentSummary(sent: {
  messages: number;
  drawing: boolean;
  drawingRequested: boolean;
}): string {
  const messages =
    sent.messages > 0
      ? `${sent.messages} of their recent message${sent.messages === 1 ? "" : "s"}`
      : null;
  if (sent.drawing) {
    return messages
      ? `Sent, with their drawing and ${messages} attached.`
      : "Sent, with their drawing attached.";
  }
  const base = messages
    ? `Sent, with ${messages} attached.`
    : "Sent. They had said nothing in this room, so there are no messages attached.";
  return sent.drawingRequested
    ? `${base} The turn had ended, so the drawing could not be attached.`
    : base;
}

const REASONS: { value: ReportReason; label: string }[] = [
  { value: "harassment", label: "Harassment or abuse" },
  { value: "offensive_drawing", label: "Offensive drawing" },
  { value: "inappropriate_name", label: "Inappropriate name" },
  { value: "cheating", label: "Cheating" },
  { value: "spam", label: "Spam" },
  { value: "inappropriate_avatar", label: "Inappropriate picture" },
];

/** Report somebody in this room.

The reported player is named by their seat; their account is never mentioned
here because the room never tells anyone what it is. Their recent messages are
attached by the server rather than picked here - a reporter should not have to
assemble evidence, and evidence they assembled would have to be checked. The
drawing is the same: when the reported player is the one drawing, the dialog
offers to include it, and the server copies the canvas as it is right now. */
export function ReportPlayerDialog({
  targetPlayerId,
  nickname,
  drawingOffered = false,
  onClose,
}: {
  targetPlayerId: string;
  nickname: string;
  /** Whether this seat is drawing right now, so the canvas can be attached. */
  drawingOffered?: boolean;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLTextAreaElement | null>(null);
  const titleId = useId();
  const [reason, setReason] = useState<ReportReason>(
    drawingOffered ? "offensive_drawing" : "harassment",
  );
  const [details, setDetails] = useState("");
  // On by default when offered: a complaint about the player drawing is
  // almost always about the drawing, and a reporter in a hurry should not
  // have to find the box.
  const [includeDrawing, setIncludeDrawing] = useState(drawingOffered);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What went, and what was asked for, as of the moment of sending. Read
  // from here rather than from the live props afterwards: the turn can end
  // while the dialog is open, which takes the offer away before the
  // confirmation renders, and the reporter who ticked the box should still
  // hear why the drawing did not come with it.
  const [sent, setSent] = useState<{
    messages: number;
    drawing: boolean;
    drawingRequested: boolean;
  } | null>(null);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: detailsRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!details.trim()) {
      setError("Say what happened, so a moderator knows what to look for.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // The reporter's choice, sent as made. If the turn has ended since
      // the box was ticked the server declines it and says so; deciding
      // that here would only hide the answer.
      const drawingRequested = includeDrawing;
      const result = await reportPlayerInRoom({
        targetPlayerId,
        reason,
        details: details.trim(),
        includeDrawing: drawingRequested,
      });
      if (!result.ok) {
        setError(result.error ?? "That report could not be sent.");
        return;
      }
      setSent({
        messages: result.evidenceCount ?? 0,
        drawing: result.drawingAttached ?? false,
        drawingRequested,
      });
    } catch (problem) {
      setError(socketRequestErrorMessage(problem, "send that report"));
    } finally {
      setBusy(false);
    }
  }

  // Portalled to the body, like the app's other floating layer. The player
  // list sits deep inside the game layout, and a dialog rendered in place is
  // trapped in that stacking context - it drew beneath the game. It was also a
  // div directly inside a <ul>, which is not somewhere a div may go.
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
      >
        <h3 id={titleId} className="modal-title">
          {sent === null ? `Report ${nickname}` : "Report sent"}
        </h3>

        {sent === null ? (
          <>
            <p className="modal-body">
              A moderator will see this. Nothing happens to {nickname} right
              now, and they are not told who reported them.
            </p>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-reason`}>What happened</label>
              <select
                id={`${titleId}-reason`}
                className="report-reason"
                value={reason}
                onChange={(change) => setReason(change.target.value as ReportReason)}
              >
                {REASONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <label htmlFor={`${titleId}-details`}>Anything else</label>
              <textarea
                id={`${titleId}-details`}
                ref={detailsRef}
                className="report-details"
                rows={3}
                maxLength={1000}
                value={details}
                onChange={(change) => {
                  setDetails(change.target.value);
                  setError(null);
                }}
                placeholder="What they said or drew, and when"
                required
              />
              <p className="auth-hint">
                Their recent messages in this room are attached automatically,
                with what was said around them.
              </p>
              {drawingOffered && (
                <label className="report-include-drawing">
                  <input
                    type="checkbox"
                    checked={includeDrawing}
                    onChange={(change) => setIncludeDrawing(change.target.checked)}
                  />
                  <span>
                    Include their drawing
                    <span>
                      The canvas as it is right now, so a moderator sees what
                      you saw.
                    </span>
                  </span>
                </label>
              )}

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
            <p className="modal-body">{sentSummary(sent)}</p>
            <button type="button" className="modal-button" onClick={onClose}>
              Done
            </button>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sent === null ? "Cancel" : "Close"}
        </button>
      </div>
    </div>,
    document.body,
  );
}
