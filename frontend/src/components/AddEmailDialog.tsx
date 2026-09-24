import { useEffect, useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
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
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const state = useEmailStateStore((store) => store.state);
  const refresh = useEmailStateStore((store) => store.refresh);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // A staff account is asked for its second factor as well (R-AUTH-26).
  const { guard, dialog: stepUpDialog } = useStepUp();
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: inputRef });

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
    <div
      className="modal-overlay"
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
          {sentTo
            ? ui.addEmailDialog.checkYourInbox
            : replacing
              ? ui.addEmailDialog.changeYourEmailAddress
              : ui.addEmailDialog.addAnEmailAddress}
        </h3>

        {sentTo ? (
          <>
            <p className="modal-body">
              {ui.addEmailDialog.followTheLink({ address: sentTo, replacing })}
            </p>
            <button
              type="button"
              className="modal-button"
              onClick={() => onSaved(sentTo)}
            >
              {ui.addEmailDialog.done}
            </button>
          </>
        ) : (
          <>
            {state && <p className="modal-body">{recoveryStatusMessage(state)}</p>}
            <p className="modal-body">
              {ui.addEmailDialog.usedOnlyResetYourPasswordTell}
            </p>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-email`}>
                {replacing ? ui.addEmailDialog.newEmail : ui.addEmailDialog.email}
              </label>
              <input
                id={`${titleId}-email`}
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
              <label htmlFor={`${titleId}-password`}>{ui.addEmailDialog.yourPassword}</label>
              <input
                id={`${titleId}-password`}
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
              <button type="submit" className="modal-button" disabled={busy}>
                {busy ? ui.addEmailDialog.pleaseWait : ui.addEmailDialog.sendConfirmation}
              </button>
            </form>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sentTo ? ui.addEmailDialog.close : ui.addEmailDialog.notNow}
        </button>
      </div>
      {stepUpDialog}
    </div>
  );
}
