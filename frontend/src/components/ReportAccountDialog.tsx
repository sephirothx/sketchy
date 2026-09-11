import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { submitPlayerReport, type ReportReason } from "../lib/moderation";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/** Report what an account itself carries: its name, or its picture.

The other two report dialogs are about something that was *said* - a seat at a
table, a line in the lobby - and both cite evidence the server picks. A name
and a picture are neither: they belong to the account, they are on every lobby
row and on the profile page, and they are visible to people who have never
been in a room with their owner. That is why this exists; until now both could
only be reported from inside a room, which is the one place they are least
likely to be met (R-AVA-06).

Nothing is cited, because there is nothing said to cite. For a picture the
server reads which one is on the account and records it, so a reviewer is told
when it has changed rather than shown a different one without comment
(R-AVA-07).

The picture is offered as a reason only when there is one: the server refuses
a complaint about a picture that does not exist, and an option that leads
somewhere refused is worse than one that is absent. A name is always there, so
it is always offered - and when it is the only reason, the dialog says so
rather than presenting a choice of one. */
export function ReportAccountDialog({
  userId,
  displayName,
  avatarUrl,
  onClose,
}: {
  userId: string;
  displayName: string;
  /** Null when the account carries no picture, which decides whether the
      picture can be complained about at all. */
  avatarUrl: string | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLTextAreaElement | null>(null);
  const reasonRef = useRef<HTMLSelectElement | null>(null);
  const titleId = useId();
  const reasons: { value: ReportReason; label: string }[] = [
    { value: "inappropriate_name", label: ui.reportAccountDialog.inappropriateName },
    ...(avatarUrl
      ? [{ value: "inappropriate_avatar" as ReportReason, label: ui.reportAccountDialog.inappropriatePicture }]
      : []),
  ];
  const [reason, setReason] = useState<ReportReason>(reasons[0].value);
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useFocusTrap(dialogRef, {
    onEscape: onClose,
    initialFocusRef: reasons.length > 1 ? reasonRef : detailsRef,
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitPlayerReport({
        reportedUserId: userId,
        reason,
        // Sent as typed, empty included: the picture is the complaint, and
        // the queue says "no details given" rather than reading a stand-in
        // as the reporter's words.
        details: details.trim(),
      });
      setSent(true);
    } catch (problem) {
      setError(
        refusalText(problem, ui.reportAccountDialog.thatReportCouldNotBeSent),
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
        data-testid="report-account-dialog"
      >
        <h3 id={titleId} className="modal-title">
          {sent ? ui.reportAccountDialog.reportSent : ui.reportAccountDialog.reportDisplayName({ displayName })}
        </h3>

        {!sent ? (
          <>
            <p className="modal-body">
              {ui.reportAccountDialog.nothingHappensYet({ name: displayName })}
            </p>
            {/* Shown only while it is what the complaint is about: a picture
                beside a complaint about a name is the wrong evidence in front
                of the person choosing. */}
            {avatarUrl && reason === "inappropriate_avatar" && (
              <figure className="report-quoted-picture" data-testid="report-quoted-picture">
                <img src={avatarUrl} alt={ui.reportAccountDialog.theirPicture({ name: displayName })} />
              </figure>
            )}
            <form onSubmit={submit} className="auth-form">
              {/* One reason is not a choice. An account with no picture can
                  only be reported for its name, and a select of one asks a
                  question with a single answer. */}
              {reasons.length > 1 ? (
                <>
                  <label htmlFor={`${titleId}-reason`}>{ui.reportAccountDialog.whatWrongWith}</label>
                  <select
                    id={`${titleId}-reason`}
                    ref={reasonRef}
                    className="report-reason"
                    value={reason}
                    onChange={(change) =>
                      setReason(change.target.value as ReportReason)
                    }
                  >
                    {reasons.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <p className="auth-hint">
                  {ui.reportAccountDialog.reportedTheirNameTheyHaveNo}
                </p>
              )}

              <label htmlFor={`${titleId}-details`}>{ui.reportAccountDialog.anythingElseOptional}</label>
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
                placeholder={ui.reportAccountDialog.anythingModeratorShouldKnow}
              />
              <p className="auth-hint">
                {reason === "inappropriate_avatar"
                  ? ui.reportAccountDialog.thePictureOnTheAccount
                  : ui.reportAccountDialog.theNameOnTheAccount}
              </p>

              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="modal-button" disabled={busy}>
                {busy ? ui.reportAccountDialog.sending : ui.reportAccountDialog.sendReport}
              </button>
            </form>
          </>
        ) : (
          <>
            <p className="modal-body">
              {ui.reportAccountDialog.sentWithWhatAboutAttached}
            </p>
            <button type="button" className="modal-button" onClick={onClose}>
              {ui.reportAccountDialog.done}
            </button>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sent ? ui.reportAccountDialog.close : ui.reportAccountDialog.cancel}
        </button>
      </div>
    </div>,
    document.body,
  );
}
