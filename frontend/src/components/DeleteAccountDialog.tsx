import { useId, useRef, useState } from "react";

import { ModalShell } from "./ui/ModalShell";
import { deleteAccount } from "../lib/accountData";
import { useAuthStore } from "../store/authStore";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

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
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const fieldId = useId();
  const formId = `${fieldId}-form`;
  const logout = useAuthStore((state) => state.logout);

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

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
        refusalText(failure, ui.deleteAccountDialog.couldNotDeleteAccount),
      );
      setDeleting(false);
    }
  }

  // Held open while the request is out: closing it then would leave the
  // account's fate unannounced.
  const dismiss = () => {
    if (!deleting) onClose();
  };

  return (
    <ModalShell
      title={isGuest ? ui.deleteAccountDialog.deleteThisGuest : ui.deleteAccountDialog.deleteYourAccount}
      cardClassName="account-delete-dialog"
      onDismiss={dismiss}
      initialFocusRef={firstFieldRef}
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={dismiss} disabled={deleting}>
            {ui.dialog.cancel}
          </button>
          <button
            type="submit"
            form={formId}
            className="btn btn-danger account-delete-confirm"
            disabled={confirmation !== CONFIRMATION || deleting}
          >
            {deleting ? ui.deleteAccountDialog.deleting : ui.deleteAccountDialog.deleteForGood}
          </button>
        </>
      }
    >
      <p className="modal-body">
        {ui.deleteAccountDialog.whatIsRemoved({ isGuest })}
      </p>
      <form id={formId} onSubmit={(event) => void submit(event)} className="auth-form account-delete-form">
        {!isGuest && (
          <>
            <label htmlFor={`${fieldId}-password`}>{ui.deleteAccountDialog.password}</label>
            <input
              id={`${fieldId}-password`}
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
        <label htmlFor={`${fieldId}-confirm`}>{ui.deleteAccountDialog.typeToConfirm({ word: CONFIRMATION })}</label>
        <input
          id={`${fieldId}-confirm`}
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
      </form>
    </ModalShell>
  );
}
