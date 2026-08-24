import { useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import {
  MAX_EMAIL_LENGTH,
  emailLooksUsable,
  setEmailAddress,
} from "../lib/accountRecovery";

/** Offer an address, which is confirmed before it counts. */
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
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: inputRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!emailLooksUsable(email)) {
      setError("That does not look like an email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { pendingAddress } = await setEmailAddress(email.trim());
      setSentTo(pendingAddress);
    } catch (submitError) {
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
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
          {sentTo ? "Check your inbox" : "Add an email address"}
        </h3>
        {sentTo ? (
          <>
            <p className="modal-body">
              Follow the link sent to {sentTo}. Until you do, the address is not
              attached to your account and cannot be used to recover it.
            </p>
            <button
              type="button"
              className="modal-button"
              onClick={() => onSaved(sentTo)}
            >
              Done
            </button>
          </>
        ) : (
          <>
            <p className="modal-body">
              Used only to reset your password and to tell you if your account
              or something you shared is actioned. Nothing else is ever sent
              here.
            </p>
            <form onSubmit={submit} className="auth-form">
              <label htmlFor={`${titleId}-email`}>Email</label>
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
              {error && (
                <p className="auth-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="modal-button" disabled={busy}>
                {busy ? "Please wait…" : "Send confirmation"}
              </button>
            </form>
          </>
        )}
        <button type="button" className="modal-dismiss" onClick={onClose}>
          {sentTo ? "Close" : "Not now"}
        </button>
      </div>
    </div>
  );
}
