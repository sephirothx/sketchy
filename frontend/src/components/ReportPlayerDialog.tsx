import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { reportPlayerInRoom, type ReportReason } from "../lib/moderation";
import { socketRequestErrorMessage } from "../lib/socket";

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
assemble evidence, and evidence they assembled would have to be checked. */
export function ReportPlayerDialog({
  targetPlayerId,
  nickname,
  onClose,
}: {
  targetPlayerId: string;
  nickname: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLTextAreaElement | null>(null);
  const titleId = useId();
  const [reason, setReason] = useState<ReportReason>("harassment");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<number | null>(null);

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
      const result = await reportPlayerInRoom({
        targetPlayerId,
        reason,
        details: details.trim(),
      });
      if (!result.ok) {
        setError(result.error ?? "That report could not be sent.");
        return;
      }
      setSent(result.evidenceCount ?? 0);
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
                Their recent messages in this room are attached automatically.
              </p>

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
            <p className="modal-body">
              {sent > 0
                ? `Sent, with ${sent} of their recent message${sent === 1 ? "" : "s"} attached.`
                : "Sent. They had said nothing in this room, so there are no messages attached."}
            </p>
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
