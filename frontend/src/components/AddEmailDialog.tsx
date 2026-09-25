import { useEffect, useId, useRef, useState } from "react";

import { ModalShell } from "./ui/ModalShell";
import { STEP_UP_ABANDONED, useStepUp } from "../hooks/useStepUp";
import {
  MAX_EMAIL_LENGTH,
  emailLooksUsable,
  recoveryStatusMessage,
  setEmailAddress,
} from "../lib/accountRecovery";
import { useEmailStateStore } from "../store/emailStateStore";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/** Add, replace, or just look at the address an account is recovered through.

Reachable from the account menu at any time, not only from the reminder: the
reminder is a prompt, and a prompt you have dismissed is not a place to go back
to. Whatever is typed here is confirmed before it counts, so an address on the
account is always one somebody has proved they can read. */
export function AddEmailDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (address: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const fieldId = useId();
  const formId = `${fieldId}-form`;
  const state = useEmailStateStore((store) => store.state);
  const refresh = useEmailStateStore((store) => store.refresh);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // A staff account is asked for its second factor as well (R-AUTH-26).
  const { guard, dialog: stepUpDialog } = useStepUp();
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Read afresh on opening, so what is already on the account is current.
  // A failed read is not worth an error of its own: the form below still
  // works, it just cannot say what is already there.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!emailLooksUsable(email)) {
      setError(ui.addEmailDialog.thatDoesNotLookLikeEmail);
      return;
    }
    if (!password) {
      setError(ui.addEmailDialog.enterYourPasswordToConfirm);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await guard(() => setEmailAddress(email.trim(), password));
      if (result === STEP_UP_ABANDONED) return;
      setSentTo(result.pendingAddress);
      setPassword("");
      void refresh();
    } catch (submitError) {
      setError(
        refusalText(submitError, ui.addEmailDialog.somethingWentWrongPleaseTryAgain),
      );
    } finally {
      setBusy(false);
    }
  }

  const replacing = Boolean(state?.verified);

  return (
    <>
      <ModalShell
        title={
          sentTo
            ? ui.addEmailDialog.checkYourInbox
            : replacing
              ? ui.addEmailDialog.changeYourEmailAddress
              : ui.addEmailDialog.addAnEmailAddress
        }
        onDismiss={onClose}
        initialFocusRef={inputRef}
        footer={
          sentTo ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onSaved(sentTo)}
            >
              {ui.addEmailDialog.done}
            </button>
          ) : (
            <>
              {/* A deferral: the reminder that opens this comes back. */}
              <button type="button" className="btn btn-secondary" onClick={onClose}>
                {ui.addEmailDialog.notNow}
              </button>
              <button type="submit" form={formId} className="btn btn-primary" disabled={busy}>
                {busy ? ui.addEmailDialog.pleaseWait : ui.addEmailDialog.sendConfirmation}
              </button>
            </>
          )
        }
      >
        {sentTo ? (
          <p className="modal-body">
            {ui.addEmailDialog.followTheLink({ address: sentTo, replacing })}
          </p>
        ) : (
          <>
            {state && <p className="modal-body">{recoveryStatusMessage(state)}</p>}
            <p className="modal-body">
              {ui.addEmailDialog.usedOnlyResetYourPasswordTell}
            </p>
            <form id={formId} onSubmit={submit} className="auth-form">
              <label htmlFor={`${fieldId}-email`}>
                {replacing ? ui.addEmailDialog.newEmail : ui.addEmailDialog.email}
              </label>
              <input
                id={`${fieldId}-email`}
                ref={inputRef}
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setError(null);
                }}
                maxLength={MAX_EMAIL_LENGTH}
                autoComplete="email"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                required
              />
              <label htmlFor={`${fieldId}-password`}>{ui.addEmailDialog.yourPassword}</label>
              <input
                id={`${fieldId}-password`}
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                autoComplete="current-password"
                required
              />
              <p className="modal-hint">{ui.addEmailDialog.passwordConfirmsItIsYou}</p>
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
            </form>
          </>
        )}
      </ModalShell>
      {stepUpDialog}
    </>
  );
}
