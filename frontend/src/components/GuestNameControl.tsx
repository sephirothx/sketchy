import { useEffect, useId, useRef, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { emitWithAck } from "../lib/socket";
import { ApiError } from "../lib/api";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import type { AckResponse } from "../types";

/**
 * "Playing as X" with an inline rename.
 *
 * Guests are handed a name rather than asked for one, so this is the only
 * place a name is ever entered - and it is never a gate on playing. Editing
 * happens in place rather than in a dialog, because changing your name is not
 * a decision that justifies interrupting anything.
 */
export function GuestNameControl({
  variant = "chip",
}: {
  /**
   * "chip" is the roomy header form. "compact" is a bare pencil for dense
   * places like your own row in the player list, where the name is already
   * on screen right next to it.
   */
  variant?: "chip" | "compact";
} = {}) {
  const user = useAuthStore((s) => s.user);
  const setDisplayName = useAuthStore((s) => s.setDisplayName);
  const playerId = useGameStore((s) => s.playerId);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const fieldId = useId();

  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isEditing) inputRef.current?.select();
  }, [isEditing]);

  // Registered players play as their username, so there is nothing to rename.
  if (!user || !user.isAnonymous) return null;

  function startEditing() {
    setValue(user!.displayName);
    setError(null);
    setIsEditing(true);
  }

  async function commit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const nickname = value.trim();
    if (nickname === user!.displayName) {
      setIsEditing(false);
      return;
    }
    const invalid = nicknameError(nickname);
    if (invalid) {
      setError(invalid);
      return;
    }

    setBusy(true);
    try {
      // In a room the socket owns the change: it validates, stores the name on
      // the account, and tells the other players. Outside one there is no
      // room to update, so the account is written directly.
      if (playerId) {
        const response = await emitWithAck<AckResponse & { nickname?: string }>(
          "rename_player",
          { nickname },
        );
        if (!response.ok) {
          setError(response.error || "Could not change your name.");
          return;
        }
        await useAuthStore.getState().fetchMe();
      } else {
        await setDisplayName(nickname);
      }
      setIsEditing(false);
    } catch (renameError) {
      setError(
        renameError instanceof ApiError
          ? renameError.message
          : "Could not change your name. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!isEditing) {
    if (variant === "compact") {
      return (
        <button
          type="button"
          className="guest-name-edit"
          onClick={startEditing}
          title="Change your name"
          aria-label="Change your name"
        >
          <span aria-hidden="true">✎</span>
        </button>
      );
    }
    return (
      <button
        type="button"
        className="guest-name-chip"
        onClick={startEditing}
        aria-label={`You are playing as ${user.displayName}. Change your name.`}
      >
        <span className="guest-name-label">Playing as</span>
        <span className="guest-name-value">{user.displayName}</span>
        <span className="guest-name-pencil" aria-hidden="true">✎</span>
      </button>
    );
  }

  return (
    <form
      className={
        variant === "compact" ? "guest-name-form is-compact" : "guest-name-form"
      }
      onSubmit={commit}
    >
      <label className="sr-only" htmlFor={fieldId}>Your name</label>
      <input
        id={fieldId}
        ref={inputRef}
        type="search"
        inputMode="text"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setIsEditing(false);
        }}
        maxLength={MAX_NICKNAME_LENGTH}
        autoComplete="nickname"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="done"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-error` : undefined}
      />
      <button type="submit" className="guest-name-save" disabled={busy}>
        {busy ? "…" : "Save"}
      </button>
      <button
        type="button"
        className="guest-name-cancel"
        onClick={() => setIsEditing(false)}
      >
        Cancel
      </button>
      {error && (
        <p id={`${fieldId}-error`} className="auth-error" role="alert">{error}</p>
      )}
    </form>
  );
}
