import { useId, useRef, useState } from "react";

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { deleteAccount } from "../lib/accountData";
import { useAuthStore } from "../store/authStore";

const CONFIRMATION = "DELETE";

/**
 * Deleting the account, on its own.
 *
 * It used to be the bottom section of a dialog called "Your data", which is
 * where an irreversible act is least expected to be. Its own row and its own
 * dialog now, with the password and the typed word asked for together rather
 * than behind a further "Delete account…" step - the row that opened this
 * already was that step. A guest has no password (R-PRIV-04): possession of
 * the session is their only credential, so the typed word is all there is.
 */
export function DeleteAccountDialog({
  isGuest,
  onClose,
}: {
  isGuest: boolean;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const logout = useAuthStore((state) => state.logout);

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: firstFieldRef });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (confirmation !== CONFIRMATION || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteAccount(isGuest ? undefined : password);
      onClose();
      // Releases any live seat, provisions a clean guest, and reconnects the
      // socket under the replacement identity.
      await logout();
    } catch (failure) {
      setError(
        failure instanceof ApiError ? failure.message : "Could not delete the account.",
      );
      setDeleting(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deleting) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card account-delete-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">
          {isGuest ? "Delete this guest" : "Delete your account"}
        </h3>
        <p className="modal-body">
          {isGuest
            ? "The name, the points and the history kept against this browser are removed. "
            : "Your name is removed from the games you played. "}
          The scores and drawings stay, under “Deleted player”, because they are other
          people’s games too. This cannot be undone.
        </p>
        <form onSubmit={(event) => void submit(event)} className="auth-form account-delete-form">
          {!isGuest && (
            <>
              <label htmlFor={`${titleId}-password`}>Password</label>
              <input
                id={`${titleId}-password`}
                ref={firstFieldRef}
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError(null);
                }}
                autoComplete="current-password"
                required
              />
            </>
          )}
          <label htmlFor={`${titleId}-confirm`}>Type {CONFIRMATION} to confirm</label>
          <input
            id={`${titleId}-confirm`}
            ref={isGuest ? firstFieldRef : undefined}
            type="text"
            value={confirmation}
            onChange={(event) => {
              setConfirmation(event.target.value);
              setError(null);
            }}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            required
          />
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="modal-button account-delete-confirm"
            disabled={confirmation !== CONFIRMATION || deleting}
          >
            {deleting ? "Deleting…" : "Delete for good"}
          </button>
        </form>
        <button type="button" className="modal-dismiss" onClick={onClose} disabled={deleting}>
          {isGuest ? "Keep playing" : "Keep my account"}
        </button>
      </div>
    </div>
  );
}
