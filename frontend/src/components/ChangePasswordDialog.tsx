import { useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { changePassword, requestPasswordReset } from "../lib/accountRecovery";
import { useToast } from "../lib/toast";

const MIN_PASSWORD_LENGTH = 8;

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
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const currentRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const { notify } = useToast();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mailed, setMailed] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: currentRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(`A password needs at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (next !== confirm) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      notify("Password changed. Every other device has been signed out.", "success");
      onClose();
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "Could not change the password. Please try again.",
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
          {mailed ? "Check your inbox" : "Change your password"}
        </h3>

        {mailed ? (
          <>
            <p className="modal-body">
              If that account has a verified email address, a link to set a new
              password is on its way. It works once, and it expires.
            </p>
            <button type="button" className="modal-button" onClick={onClose}>
              Done
            </button>
          </>
        ) : (
          <>
            <p className="modal-body">
              Every device signs out when the password changes, including any you
              did not mean to leave signed in. This one stays.
            </p>
            <form onSubmit={(event) => void submit(event)} className="auth-form">
              <label htmlFor={`${titleId}-current`}>Current password</label>
              <input
                id={`${titleId}-current`}
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
              <label htmlFor={`${titleId}-next`}>New password</label>
              <input
                id={`${titleId}-next`}
                type="password"
                value={next}
                onChange={(event) => {
                  setNext(event.target.value);
                  setError(null);
                }}
                autoComplete="new-password"
                minLength={MIN_PASSWORD_LENGTH}
                required
              />
              <label htmlFor={`${titleId}-confirm`}>New password again</label>
              <input
                id={`${titleId}-confirm`}
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
              <button type="submit" className="modal-button" disabled={busy}>
                {busy ? "Please wait…" : "Change password"}
              </button>
            </form>
            {/* The other way to do the same job, for somebody who does not
                know the current password. Hidden rather than dead when there
                is no verified address, because the link could not arrive. */}
            {canEmailLink && (
              <p className="modal-body settings-alt-route">
                Forgotten the current one?{" "}
                <button
                  type="button"
                  className="auth-link"
                  disabled={busy}
                  onClick={() => void mailLink()}
                >
                  Email me a link instead
                </button>
              </p>
            )}
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>
          {mailed ? "Close" : "Cancel"}
        </button>
      </div>
    </div>
  );
}
