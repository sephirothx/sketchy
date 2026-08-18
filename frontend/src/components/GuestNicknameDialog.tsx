import { useId, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { ApiError } from "../lib/api";
import { useAuthStore } from "../store/authStore";

/**
 * Asks a guest what to be called, at the moment they first create or join a
 * room rather than on arrival.
 *
 * Nothing here is a gate on playing: the name is required, but no account is.
 * The "log in" affordance matters because this dialog can cover the header,
 * and a returning player must be able to reach their account from it.
 */
export function GuestNicknameDialog({
  initialNickname,
  onConfirm,
  onCancel,
  onLogin,
}: {
  initialNickname: string;
  onConfirm: (nickname: string) => void;
  onCancel: () => void;
  onLogin: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const [value, setValue] = useState(initialNickname);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onCancel, initialFocusRef: inputRef });

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    const nickname = value.trim();
    const invalid = nicknameError(nickname);
    if (invalid) {
      setError(invalid);
      return;
    }

    setChecking(true);
    try {
      // Remembering the choice server-side also enforces it: a name already
      // claimed by a registered player is rejected here.
      await useAuthStore.getState().setDisplayName(nickname);
    } catch (saveError) {
      const status = saveError instanceof ApiError ? saveError.status : 0;
      if (status === 409 || status === 400) {
        setError(
          saveError instanceof ApiError
            ? saveError.message
            : "That name is not available.",
        );
        setChecking(false);
        return;
      }
      // Offline or the server is down. Play anyway: create and join both
      // re-check the name, so nothing can slip through unvalidated.
    } finally {
      setChecking(false);
    }
    onConfirm(nickname);
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
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
        <h3 id={titleId} className="modal-title">Pick a name</h3>
        <p className="modal-body">This is how other players will see you.</p>

        <form onSubmit={confirm} className="auth-form">
          <label htmlFor={`${titleId}-nickname`}>Name</label>
          {/* Same input contract as the rest of the app: search type suppresses
              Android Chrome's autofill toolbar, and autoCapitalize is off
              because names are case-sensitive and cannot contain spaces. */}
          <input
            id={`${titleId}-nickname`}
            ref={inputRef}
            type="search"
            inputMode="text"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setError(null);
            }}
            maxLength={MAX_NICKNAME_LENGTH}
            autoComplete="nickname"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            required
          />
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button type="submit" className="modal-button" disabled={checking}>
            {checking ? "Checking…" : "Play"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account?{" "}
          <button type="button" className="auth-link" onClick={onLogin}>
            Log in
          </button>
        </p>
      </div>
    </div>
  );
}
