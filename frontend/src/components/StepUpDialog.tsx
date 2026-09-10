import { useRef, useState } from "react";

import { SegmentedCodeInput } from "./SegmentedCodeInput";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { assertPasskey, passkeysAvailable } from "../lib/passkeys";
import { stepUp } from "../lib/secondFactor";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

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
  const titleId = useRef(`step-up-${Math.random().toString(36).slice(2)}`).current;
  const [code, setCode] = useState("");
  // A recovery code is ten letters and digits, so it cannot go in the six
  // numeric boxes - and the server takes one here, which is the whole point
  // of having them when the authenticator is the thing you have lost.
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canUsePasskeys = passkeysAvailable();

  useFocusTrap(dialogRef, { active: true, onEscape: onCancel });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await submitWith(code);
  }

  /** Takes the code, for the same reason the enrolment form does: the digit
      that completes it has not reached state when the row asks to submit. */
  async function submitWith(entered: string) {
    if (busy || entered.trim().length < 6) return;
    setBusy(true);
    setError(null);
    try {
      await stepUp(entered);
      onProved();
    } catch (problem) {
      setError(refusalText(problem, ui.stepUpDialog.thatCodeWasNotAccepted));
      setBusy(false);
    }
  }

  /** The passkey route, which is the same assertion a sign-in makes. Offered
      first because it is one gesture and cannot be relayed - the code below
      is what a device with no passkey uses (R-AUTH-23). */
  async function proveWithPasskey() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await assertPasskey();
      onProved();
    } catch (problem) {
      setError(
        problem instanceof DOMException
          ? "That passkey was not used. You can try again."
          : refusalText(problem, ui.stepUpDialog.thatPasskeyWasNotAccepted),
      );
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
        <h3 id={titleId} className="modal-title">{ui.stepUpDialog.confirmYou}</h3>
        <p className="modal-body">{reason}</p>
        {error && <p className="auth-error" role="alert">{error}</p>}
        {canUsePasskeys && (
          <button
            type="button"
            className="modal-button step-up-passkey"
            onClick={() => void proveWithPasskey()}
            disabled={busy}
          >
            {busy ? "Waiting for your device…" : "Use your passkey"}
          </button>
        )}
        <form onSubmit={(event) => void submit(event)}>
          {useRecovery ? (
            <>
              <label className="two-factor-field-label" htmlFor="step-up-recovery">
                {ui.stepUpDialog.recoveryCode}
              </label>
              <input
                id="step-up-recovery"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                autoComplete="one-time-code"
                maxLength={32}
                autoFocus
                required
              />
            </>
          ) : (
            <>
              <span className="two-factor-field-label">
                {ui.stepUpDialog.codeFromYourAuthenticatorApp}
              </span>
              <SegmentedCodeInput
                value={code}
                onChange={setCode}
                onComplete={(complete) => void submitWith(complete)}
                label="Code from your authenticator app"
                autoFocus
                disabled={busy}
              />
            </>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-compact step-up-swap"
            onClick={() => {
              setUseRecovery((current) => !current);
              setCode("");
              setError(null);
            }}
          >
            {useRecovery ? "Use your authenticator app" : "Use a recovery code"}
          </button>
          <div className="step-up-actions">
            <button type="button" onClick={onCancel} disabled={busy}>{ui.stepUpDialog.cancel}</button>
            <button type="submit" disabled={busy}>{busy ? "Checking…" : "Confirm"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
