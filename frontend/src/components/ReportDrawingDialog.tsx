import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { reportGalleryDrawing } from "../lib/moderation";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/player-list.css";

/** Report a drawing met in the Gallery (R-GAL-08).

The in-room report dialog attaches the canvas only while the room still shows
it; a Gallery drawing is one the room has long since left behind, seen by
people who were never there. So there is no reason to choose - a drawing in
the Gallery can only be reported as a drawing - and nothing to cite: the
server holds the frame the Gallery shows, resolves who drew it, and copies the
stored drawing as the evidence. All that is asked here is whether the
reporter has anything to add. */
export function ReportDrawingDialog({
  turnId,
  onClose,
}: {
  turnId: string;
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
      // Sent as typed, empty included: the drawing is the complaint, and
      // the queue says "no details given" rather than reading a stand-in
      // as the reporter's words.
      await reportGalleryDrawing(turnId, details.trim());
      setSent(true);
    } catch (problem) {
      setError(refusalText(problem, ui.reportDrawingDialog.thatReportCouldNotBeSent));
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
        data-testid="report-drawing-dialog"
      >
        <h3 id={titleId} className="modal-title">
          {sent ? ui.reportDrawingDialog.reportSent : ui.reportDrawingDialog.reportThisDrawing}
        </h3>

        {!sent ? (
          <>
            <p className="modal-body">{ui.reportDrawingDialog.nothingHappensYet}</p>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-details`}>
                {ui.reportDrawingDialog.anythingElseOptional}
              </label>
              <textarea
                id={`${titleId}-details`}
                ref={detailsRef}
                className="report-details"
                rows={3}
                maxLength={2000}
                value={details}
                onChange={(change) => {
                  setDetails(change.target.value);
                  setError(null);
                }}
                placeholder={ui.reportDrawingDialog.anythingModeratorShouldKnow}
              />

              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button
                type="submit"
                className="modal-button"
                disabled={busy}
                data-testid="report-drawing-send"
              >
                {busy ? ui.reportDrawingDialog.sending : ui.reportDrawingDialog.sendReport}
              </button>
            </form>
          </>
        ) : (
          <>
            <p className="modal-body">{ui.reportDrawingDialog.sentWithTheDrawingAttached}</p>
            <button type="button" className="modal-button" onClick={onClose}>
              {ui.reportDrawingDialog.done}
            </button>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sent ? ui.reportDrawingDialog.close : ui.reportDrawingDialog.cancel}
        </button>
      </div>
    </div>,
    document.body,
  );
}
