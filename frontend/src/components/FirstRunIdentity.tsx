import { useId, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { ApiError } from "../lib/api";

/**
 * Shown only until the visitor has an account or a name of their own.
 *
 * An account is the primary action and says why; playing as a guest is one
 * field and one click below a divider - easy, but plainly the lesser path.
 * Inline rather than modal, so browsing and logging in are never gated, and
 * nothing interrupts a click the player has already made. A returning player on
 * a new device lands here and reaches "Log in" without being asked to invent a
 * guest name.
 */
export function FirstRunIdentity({ compact = false }: { compact?: boolean } = {}) {
  const user = useAuthStore((s) => s.user);
  const hasResolved = useAuthStore((s) => s.hasResolved);
  const setDisplayName = useAuthStore((s) => s.setDisplayName);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);

  const fieldId = useId();
  const [mode, setMode] = useState<AuthMode | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Nothing until the initial GET /api/auth/me settles. A null user means
  // "not known yet" as well as "nobody", and offering these controls in that
  // window lets a submission race the provisioning request: both are
  // cookieless, both create an account, and the later cookie discards the
  // name that was just chosen.
  if (!hasResolved) return null;

  // Once there is a name, or an account, this never appears again.
  const needsIdentity = !user || (user.isAnonymous && !user.displayName);
  if (!needsIdentity) return null;

  async function playAsGuest(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const chosen = name.trim();
    const invalid = nicknameError(chosen);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      await setDisplayName(chosen);
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.message
          : "Could not save that name. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={compact ? "first-run is-compact" : "first-run"}
      aria-labelledby={`${fieldId}-heading`}
    >
      <div className="first-run-primary">
        <h2 id={`${fieldId}-heading`} className="first-run-heading">
          Play as yourself
        </h2>
        <p className="first-run-copy">
          Keep your name and your stats, on every device.
        </p>
        <div className="first-run-actions">
          <button
            type="button"
            className="first-run-signup"
            onClick={() => setMode("claim")}
          >
            Create an account
          </button>
          <button
            type="button"
            className="first-run-login"
            onClick={() => setMode("login")}
          >
            Log in
          </button>
        </div>
      </div>

      <div className="first-run-divider" role="presentation">
        <span>or</span>
      </div>

      <form className="first-run-guest" onSubmit={playAsGuest}>
        <label htmlFor={`${fieldId}-name`} className="first-run-guest-label">
          Just playing once? Pick a name
        </label>
        <div className="first-run-guest-row">
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar,
              matching every other name field in the app. */}
          <input
            id={`${fieldId}-name`}
            type="search"
            inputMode="text"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setError(null);
            }}
            maxLength={MAX_NICKNAME_LENGTH}
            placeholder="Your name"
            autoComplete="nickname"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
          />
          <button type="submit" className="first-run-guest-submit" disabled={busy}>
            {busy ? "…" : "Play as guest"}
          </button>
        </div>
        {error && (
          <p id={`${fieldId}-error`} className="auth-error" role="alert">{error}</p>
        )}
      </form>

      {mode && (
        <AuthDialog
          mode={mode}
          onClose={() => setMode(null)}
          onSwitchMode={setMode}
          onSubmit={mode === "login" ? login : register}
        />
      )}
    </section>
  );
}
