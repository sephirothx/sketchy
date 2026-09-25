import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createPortal } from "react-dom";

import { ModalShell } from "./ui/ModalShell";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/** The words a reporter may add, on every report route. Mirrors the server's
    `MAX_REPORT_DETAILS` (backend/app/message_limits.py), which bounds the
    room's socket report and every REST one alike (R-MOD-01). */
export const MAX_REPORT_DETAILS = 2000;

/** The counter appears once this few characters are left: a count from the
    first keystroke is noise for a sentence or two, and the limit only matters
    to somebody about to reach it. */
const COUNTER_FROM = 200;

export interface ReportReasonChoice<R extends string> {
  value: R;
  label: string;
}

export interface ReportReasonPicker<R extends string> {
  /** The question the picker answers - "What happened", "Reason". */
  label: string;
  choices: ReportReasonChoice<R>[];
  value: R;
  onChange: (value: R) => void;
  /** Said instead of a picker when there is only one choice: a select of one
      asks a question with a single answer. */
  onlyChoice?: string;
}

interface ReportDialogProps<R extends string> {
  /** "Report <name>" - what is being reported, while the form is up. */
  title: string;
  /** What happens next, and to whom: nothing, until a moderator looks. */
  intro: string;
  testId?: string;
  sendTestId?: string;
  /** The evidence as the reporter sees it, above the form: a quoted line, a
      picture. */
  quoted?: ReactNode;
  reason?: ReportReasonPicker<R>;
  /** Fields that narrow the target, after the reason: which prompt in a list. */
  extraFields?: ReactNode;
  detailsPlaceholder?: string;
  /** What goes with the report besides the words, said under the box - which
      is also why the box may be left empty. */
  attachedHint?: string;
  /** Options after the words: attaching the canvas. */
  trailing?: ReactNode;
  /** Sends the report; resolves with the sentence the sent view shows. Throws
      a refusal (or anything else) when it did not go. */
  onSend: (details: string) => Promise<string>;
  /** How a failure reads; a refusal's own sentence by default. */
  failureText?: (problem: unknown) => string;
  onClose: () => void;
}

/** The one report dialog: a name, a picture, a line of lobby chat, a seat in a
room, a drawing in the Gallery, a prompt list.

They were five dialogs built one at a time, and a reporter could tell: the
first focus landed on the details in two, on the reason in another, on Cancel
in the last; the box stopped at 1000 characters in three and at 2000 in two,
with no counter anywhere; prompt content insisted on words the others said
were optional; and after sending, four answered in the dialog with both a Done
and a ✕ while the fifth closed and left a line on the page. The complaint is
the same act wherever it starts, so it is now the same dialog. What differs -
the target, its reasons, what the server attaches - is each caller's to say;
how it reads is decided here once.

- **First focus** is the reason picker when there is a choice to make, the
  words when there is not.
- **The words are optional** and bounded at `MAX_REPORT_DETAILS` everywhere
  (R-MOD-01): the evidence is attached by the server and is usually the whole
  complaint. A counter shows once the limit is near.
- **Sent** is said in the dialog, with one Close: the answer replaces the
  form, and the one way out takes focus so it does not drop to the page. */
export function ReportDialog<R extends string>({
  title,
  intro,
  testId,
  sendTestId,
  quoted,
  reason,
  extraFields,
  detailsPlaceholder = ui.reportDialog.anythingModeratorShouldKnow,
  attachedHint,
  trailing,
  onSend,
  failureText = (problem) => refusalText(problem, ui.reportDialog.couldNotSend),
  onClose,
}: ReportDialogProps<R>) {
  const reasonRef = useRef<HTMLSelectElement | null>(null);
  const detailsRef = useRef<HTMLTextAreaElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const fieldId = useId();
  const formId = `${fieldId}-form`;
  const counterId = `${fieldId}-counter`;
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const picking = reason !== undefined && reason.choices.length > 1;
  const left = MAX_REPORT_DETAILS - details.length;
  const counting = left <= COUNTER_FROM;

  // Sending swaps the form for the answer, and the submit button that held
  // focus goes with it; focus follows to Close rather than dropping to the page.
  useEffect(() => {
    if (sent !== null) closeRef.current?.focus();
  }, [sent]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // Sent as typed, empty included: the evidence is the complaint, and
      // the queue says "no details given" rather than reading a stand-in as
      // the reporter's words.
      setSent(await onSend(details.trim()));
    } catch (problem) {
      setError(failureText(problem));
    } finally {
      setBusy(false);
    }
  }

  // Portalled to the body: a report is opened from deep inside the game
  // layout, the players drawer and the lobby's lists, and a dialog rendered in
  // place is trapped in their stacking contexts.
  return createPortal(
    <ModalShell
      title={sent === null ? title : ui.reportDialog.reportSent}
      overlayClassName="report-player-overlay"
      testId={testId}
      onDismiss={onClose}
      // Once sent, the footer's Close is the one way out; Escape and the scrim
      // still dismiss, as they do everywhere.
      closeButton={sent === null}
      initialFocusRef={picking ? reasonRef : detailsRef}
      footer={
        sent === null ? (
          <>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              {ui.dialog.cancel}
            </button>
            <button
              type="submit"
              form={formId}
              className="btn btn-primary"
              disabled={busy}
              data-testid={sendTestId}
            >
              {busy ? ui.reportDialog.sending : ui.reportDialog.sendReport}
            </button>
          </>
        ) : (
          <button ref={closeRef} type="button" className="btn btn-primary" onClick={onClose}>
            {ui.dialog.close}
          </button>
        )
      }
    >
      {sent === null ? (
        <>
          <p className="modal-body">{intro}</p>
          {quoted}
          <form id={formId} onSubmit={(event) => void submit(event)} className="auth-form">
            {reason && picking && (
              <>
                <label htmlFor={`${fieldId}-reason`}>{reason.label}</label>
                <select
                  id={`${fieldId}-reason`}
                  ref={reasonRef}
                  className="report-reason"
                  value={reason.value}
                  onChange={(change) => reason.onChange(change.target.value as R)}
                >
                  {reason.choices.map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </>
            )}
            {reason && !picking && reason.onlyChoice && (
              <p className="auth-hint">{reason.onlyChoice}</p>
            )}
            {extraFields}

            <label htmlFor={`${fieldId}-details`}>{ui.reportDialog.anythingElseOptional}</label>
            <textarea
              id={`${fieldId}-details`}
              ref={detailsRef}
              className="report-details"
              rows={3}
              maxLength={MAX_REPORT_DETAILS}
              value={details}
              aria-describedby={counting ? counterId : undefined}
              onChange={(change) => {
                setDetails(change.target.value);
                setError(null);
              }}
              placeholder={detailsPlaceholder}
            />
            {counting && (
              <p id={counterId} className="report-counter" data-testid="report-counter">
                {ui.reportDialog.charactersLeft({ count: left })}
              </p>
            )}
            {attachedHint && <p className="auth-hint">{attachedHint}</p>}
            {trailing}

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
          </form>
        </>
      ) : (
        <p className="modal-body">{sent}</p>
      )}
    </ModalShell>,
    document.body,
  );
}
