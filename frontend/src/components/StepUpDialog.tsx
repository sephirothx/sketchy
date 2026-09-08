import { useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { stepUp } from "../lib/secondFactor";

/**
 * The prompt a staff action raises when it needs the second factor again.
 *
 * Shown in response to a refusal rather than before the action (R-AUTH-21):
 * the server decides whether the window is still open, and a client that
 * guessed would either ask when it did not need to or let somebody type a
 * suspension reason before finding out they had to prove themselves.
 *
 * `onProved` is the action that was refused, retried. Nothing is queued or
 * replayed automatically — the caller holds what it was doing.
 */
export function StepUpDialog({
  reason,
  onProved,
  onCancel,
}: {
  reason: string;
  onProved: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const codeId = useId();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusTrap(dialogRef, { active: true, onEscape: onCancel, initialFocusRef: inputRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await stepUp(code);
      onProved();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : "That code was not accepted.");
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay">
      <div
        ref={dialogRef}
        className="modal-card step-up"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">Confirm it is you</h3>
        <p className="modal-body">{reason}</p>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <form onSubmit={(event) => void submit(event)}>
          <label htmlFor={codeId}>Code from your authenticator app</label>
          <input
            id={codeId}
            ref={inputRef}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={64}
            required
          />
          <div className="step-up-actions">
            <button type="button" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" disabled={busy}>{busy ? "Checking…" : "Confirm"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
