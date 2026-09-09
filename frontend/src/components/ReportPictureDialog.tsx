import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { submitPlayerReport } from "../lib/moderation";

/** Report the picture on somebody's account.

The other two report dialogs are about something that was *said* - a seat at a
table, a line in the lobby - and both cite evidence the server picks. A picture
is neither: it belongs to the account, it is on every lobby row and on the
profile page, and it is visible to people who have never been in a room with
its owner. That is why this exists at all; until now a picture could only be
reported from inside a room, which is the one place it is least likely to be
seen (R-AVA-04).

So there is no reason to choose - the control says what it is for, and
`inappropriate_avatar` is the only thing it can mean - and nothing to cite: the
server reads which picture is on the account and records it, so a reviewer is
told when it has changed rather than shown a different one without comment. */
export function ReportPictureDialog({
  userId,
  displayName,
  avatarUrl,
  onClose,
}: {
  userId: string;
  displayName: string;
  /** Held apart from the name so a caller cannot open this for an account
      with no picture, which the server refuses anyway. */
  avatarUrl: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLTextAreaElement | null>(null);
  const titleId = useId();
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: detailsRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitPlayerReport({
        reportedUserId: userId,
        reason: "inappropriate_avatar",
        // Sent as typed, empty included: the picture is the complaint, and
        // the queue says "no details given" rather than reading a stand-in
        // as the reporter's words.
        details: details.trim(),
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
        data-testid="report-picture-dialog"
      >
        <h3 id={titleId} className="modal-title">
          {sent ? "Report sent" : `Report ${displayName}'s picture`}
        </h3>

        {!sent ? (
          <>
            <p className="modal-body">
              A moderator will see this picture. Nothing happens to {displayName}{" "}
              right now, and they are not told who reported them.
            </p>
            <figure className="report-quoted-picture" data-testid="report-quoted-picture">
              <img src={avatarUrl} alt={`${displayName}'s picture`} />
            </figure>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-details`}>Anything else (optional)</label>
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
                placeholder="Anything a moderator should know"
              />
              <p className="auth-hint">
                The picture on the account is attached as it stands now.
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
            <p className="modal-body">Sent, with the picture attached.</p>
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
