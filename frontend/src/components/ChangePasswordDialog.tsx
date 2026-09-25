import { useEffect, useId, useRef, useState } from "react";

import { ModalShell } from "./ui/ModalShell";
import { changePassword, requestPasswordReset } from "../lib/accountRecovery";
import { reconnectWithCurrentIdentity } from "../lib/socket";
import { useToast } from "../lib/toast";
import { MIN_PASSWORD_LENGTH, passwordRule, passwordTooShort } from "../lib/passwordPolicy";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/settings.css";



/**
 * Changing a password you still know (R-AUTH-17).
 *
 * The reset link exists for the other case - you have forgotten it - so this
 * dialog offers that too rather than sending anybody to the sign-in page to
 * pretend they are locked out. The mailed route needs a verified address to
 * arrive at (R-AUTH-07), so it is offered only when there is one.
 *
 * Every session is signed out by the change, this one included; the server
 * hands the caller a fresh one back, so the only visible effect is that other
 * devices have to sign in again. That is said before the button, because a
 * password change is also how somebody evicts a device they no longer trust.
 */
export function ChangePasswordDialog({
  username,
  canEmailLink,
  onClose,
}: {
  username: string;
  /** A verified address exists for the link to arrive at. */
  canEmailLink: boolean;
  onClose: () => void;
}) {
  const currentRef = useRef<HTMLInputElement | null>(null);
  const fieldId = useId();
  const formId = `${fieldId}-form`;
  const doneRef = useRef<HTMLButtonElement | null>(null);
  const { notify } = useToast();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mailed, setMailed] = useState(false);

  // The form goes once it has worked, and focus with it; Done is where it
  // lands rather than on the page behind.
  useEffect(() => {
    if (mailed) doneRef.current?.focus();
  }, [mailed]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(passwordTooShort());
      return;
    }
    if (next !== confirm) {
      setError(ui.changePasswordDialog.twoNewPasswordsDoNotMatch);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      // Every other device's socket was closed by the server; this one was
      // kept, and handshakes again with the cookie the response just set,
      // so it remembers the session it now belongs to (#1007).
      reconnectWithCurrentIdentity();
      notify(ui.changePasswordDialog.passwordChangedEveryOtherDeviceHas, "success");
      onClose();
    } catch (failure) {
      setError(
        refusalText(failure, ui.changePasswordDialog.couldNotChangePasswordPleaseTry),
      );
      setBusy(false);
    }
  }

  async function mailLink() {
    if (busy) return;
    setBusy(true);
    // The reply is deliberately the same whether or not the account exists
    // (R-AUTH-09), so there is nothing here to branch on.
    await requestPasswordReset(username).catch(() => {});
    setBusy(false);
    setMailed(true);
  }

  return (
    <ModalShell
      title={mailed ? ui.changePasswordDialog.checkYourInbox : ui.changePasswordDialog.changeYourPassword}
      onDismiss={onClose}
      initialFocusRef={currentRef}
      footer={
        mailed ? (
          <button ref={doneRef} type="button" className="btn btn-primary" onClick={onClose}>
            {ui.changePasswordDialog.done}
          </button>
        ) : (
          <>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              {ui.changePasswordDialog.cancel}
            </button>
            <button type="submit" form={formId} className="btn btn-primary" disabled={busy}>
              {busy ? ui.changePasswordDialog.pleaseWait : ui.changePasswordDialog.changePassword}
            </button>
          </>
        )
      }
    >
      {mailed ? (
        <p className="modal-body">
          {ui.changePasswordDialog.ifThatAccountHasVerifiedEmail}
        </p>
      ) : (
        <>
          <p className="modal-body">
            {ui.changePasswordDialog.everyDeviceSignsOutWhenPassword}
          </p>
          <form id={formId} onSubmit={(event) => void submit(event)} className="auth-form">
            <label htmlFor={`${fieldId}-current`}>{ui.changePasswordDialog.currentPassword}</label>
            <input
              id={`${fieldId}-current`}
              ref={currentRef}
              type="password"
              value={current}
              onChange={(event) => {
                setCurrent(event.target.value);
                setError(null);
              }}
              autoComplete="current-password"
              required
            />
            <label htmlFor={`${fieldId}-next`}>{ui.changePasswordDialog.newPassword}</label>
            <input
              id={`${fieldId}-next`}
              type="password"
              value={next}
              onChange={(event) => {
                setNext(event.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              minLength={MIN_PASSWORD_LENGTH}
              aria-describedby={`${fieldId}-rule`}
              required
            />
            <p id={`${fieldId}-rule`} className="auth-hint">{passwordRule()}</p>
            <label htmlFor={`${fieldId}-confirm`}>{ui.changePasswordDialog.newPasswordAgain}</label>
            <input
              id={`${fieldId}-confirm`}
              type="password"
              value={confirm}
              onChange={(event) => {
                setConfirm(event.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              required
            />
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
          </form>
          {/* The other way to do the same job, for somebody who does not
              know the current password. Hidden rather than dead when there
              is no verified address, because the link could not arrive. */}
          {canEmailLink && (
            <p className="modal-body settings-alt-route">
              {ui.changePasswordDialog.forgottenTheCurrentOne}{" "}
              <button
                type="button"
                className="auth-link"
                disabled={busy}
                onClick={() => void mailLink()}
              >
                {ui.changePasswordDialog.emailMeLinkInstead}
              </button>
            </p>
          )}
        </>
      )}
    </ModalShell>
  );
}
