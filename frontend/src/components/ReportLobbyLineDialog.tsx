import { useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ModalShell } from "./ui/ModalShell";
import type { LobbyChatLine } from "../lib/lobbyChat";
import { submitPlayerReport, type ReportReason } from "../lib/moderation";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/** The reasons a line of chat can be reported for. A line is words, so the
reasons about a drawing, a picture, or play are left out rather than offered
and never true. */
const REASONS: { value: ReportReason; label: string }[] = [
  { value: "harassment", get label() { return ui.reportLobbyLineDialog.harassmentOrAbuse; } },
  { value: "spam", get label() { return ui.reportLobbyLineDialog.spam; } },
  { value: "inappropriate_name", get label() { return ui.reportLobbyLineDialog.inappropriateName; } },
];

/** Report a line of the lobby's chat.

The room's dialog names a seat and lets the server pick the evidence. The
lobby has no seat - a line carries its author's account id for exactly this
reason (R-ROOM-07) - so this one goes over REST, names the account, and cites
the one line it was opened from; the server adds what the lobby said around
it, as it does for a room. The line is shown here so the reporter sees what
they are citing. */
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
  const reasonRef = useRef<HTMLSelectElement | null>(null);
  const titleId = useId();
  const formId = `${titleId}-form`;
  const [reason, setReason] = useState<ReportReason>("harassment");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await submitPlayerReport({
        reportedUserId: line.userId,
        reason,
        // Sent as typed, empty included: the line itself is the complaint,
        // and the queue says "no details given" rather than reading a
        // stand-in as the reporter's words.
        details: details.trim(),
        messageIds: [retainedMessageId],
      });
      setSent(true);
    } catch (problem) {
      setError(
        refusalText(problem, ui.reportLobbyLineDialog.thatReportCouldNotBeSent),
      );
    } finally {
      setBusy(false);
    }
  }

  // Portalled like the room's report dialog, and given its overlay class so it
  // sits on the same layer.
  return createPortal(
    <ModalShell
      title={sent ? ui.reportLobbyLineDialog.reportSent : ui.reportLobbyLineDialog.reportDisplayName({ displayName: line.displayName })}
      overlayClassName="report-player-overlay"
      testId="report-lobby-line-dialog"
      onDismiss={onClose}
      initialFocusRef={reasonRef}
      footer={
        !sent ? (
          <>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              {ui.reportLobbyLineDialog.cancel}
            </button>
            <button
              type="submit"
              form={formId}
              className="btn btn-primary"
              disabled={busy}
            >
              {busy ? ui.reportLobbyLineDialog.sending : ui.reportLobbyLineDialog.sendReport}
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-primary" onClick={onClose}>
            {ui.reportLobbyLineDialog.done}
          </button>
        )
      }
    >
      {!sent ? (
        <>
          <p className="modal-body">
            {ui.reportLobbyLineDialog.nothingHappensYet({ name: line.displayName })}
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
          <form id={formId} onSubmit={submit} className="auth-form">
            <label htmlFor={`${titleId}-reason`}>{ui.reportLobbyLineDialog.whatWrongWith}</label>
            <select
              id={`${titleId}-reason`}
              ref={reasonRef}
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

            <label htmlFor={`${titleId}-details`}>{ui.reportLobbyLineDialog.anythingElseOptional}</label>
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
              placeholder={ui.reportLobbyLineDialog.anythingModeratorShouldKnow}
            />
            <p className="auth-hint">
              {ui.reportLobbyLineDialog.thisLineAttachedWithWhatLobby}
            </p>

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
          </form>
        </>
      ) : (
        <p className="modal-body">{ui.reportLobbyLineDialog.sentWithLineWhatWasSaid}</p>
      )}
    </ModalShell>,
    document.body,
  );
}
