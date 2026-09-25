import { useId, useState } from "react";

import { SegmentedCodeInput } from "./SegmentedCodeInput";
import { ModalShell } from "./ui/ModalShell";
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
  const formId = useId();
  const [code, setCode] = useState("");
  // A recovery code is ten letters and digits, so it cannot go in the six
  // numeric boxes - and the server takes one here, which is the whole point
  // of having them when the authenticator is the thing you have lost.
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canUsePasskeys = passkeysAvailable();

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
          ? ui.stepUpDialog.passkeyNotUsed
          : refusalText(problem, ui.stepUpDialog.thatPasskeyWasNotAccepted),
      );
      setBusy(false);
    }
  }

  // The scrim does not cancel: this interrupts an action the caller is
  // holding, and a stray click should not be what abandons it.
  return (
    <ModalShell
      title={ui.stepUpDialog.confirmYou}
      cardClassName="step-up"
      onDismiss={onCancel}
      dismissOnBackdrop={false}
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            {ui.stepUpDialog.cancel}
          </button>
          <button type="submit" form={formId} className="btn btn-primary" disabled={busy}>
            {busy ? ui.stepUpDialog.checking : ui.stepUpDialog.confirm}
          </button>
        </>
      }
    >
      <p className="modal-body">{reason}</p>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {canUsePasskeys && (
        <button
          type="button"
          className="btn btn-secondary step-up-passkey"
          onClick={() => void proveWithPasskey()}
          disabled={busy}
        >
          {busy ? ui.stepUpDialog.waitingForYourDevice : ui.stepUpDialog.useYourPasskey}
        </button>
      )}
      <form id={formId} onSubmit={(event) => void submit(event)}>
        {useRecovery ? (
          <>
            <label className="two-factor-field-label" htmlFor={`${formId}-recovery`}>
              {ui.stepUpDialog.recoveryCode}
            </label>
            <input
              id={`${formId}-recovery`}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              autoComplete="one-time-code"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
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
              label={ui.stepUpDialog.codeFromYourAuthenticatorApp2}
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
          {useRecovery ? ui.stepUpDialog.useYourAuthenticatorApp : ui.stepUpDialog.useARecoveryCode}
        </button>
      </form>
    </ModalShell>
  );
}
