import { useId, useRef, useState, type FormEvent } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { apiRequest } from "../lib/api";
import { registeredNicknameTakenMessage } from "../lib/guestNickname";
import { MAX_NICKNAME_LENGTH } from "../lib/roomEntryState";

export function GuestNicknameDialog({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (nickname: string) => void;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusTrap(dialogRef, {
    onEscape: onCancel,
    initialFocusRef: inputRef,
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const nickname = value.trim();
    if (!nickname) {
      setError("Please enter a nickname");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await apiRequest<{ available: boolean }>(
        `/api/auth/nickname-available?${new URLSearchParams({ nickname })}`,
      );
      if (!data.available) {
        setError(registeredNicknameTakenMessage(nickname));
        return;
      }
      onSubmit(nickname);
    } catch {
      setError("Could not check that nickname. Please try again.");
    } finally {
      setBusy(false);
    }
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
        className="modal-card guest-nickname-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">Choose a nickname</h3>
        <p id={descriptionId} className="modal-body">
          Pick a name to play as a guest. You can create an account later to keep it and your stats.
        </p>
        <form className="guest-nickname-form" onSubmit={handleSubmit}>
          <label htmlFor="guest-nickname-input">Nickname</label>
          <input
            ref={inputRef}
            id="guest-nickname-input"
            type="search"
            inputMode="text"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              if (error) setError(null);
            }}
            maxLength={MAX_NICKNAME_LENGTH}
            placeholder="Your name"
            autoComplete="nickname"
            autoCapitalize="words"
            spellCheck={false}
            autoCorrect="off"
            enterKeyHint="done"
            disabled={busy}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "guest-nickname-error" : undefined}
          />
          {error && (
            <p id="guest-nickname-error" className="invite-form-error" role="alert">{error}</p>
          )}
          <div className="guest-nickname-actions">
            <button type="submit" className="modal-button" disabled={busy}>
              {busy ? "Checking…" : "Continue"}
            </button>
            <button type="button" className="account-dialog-secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
