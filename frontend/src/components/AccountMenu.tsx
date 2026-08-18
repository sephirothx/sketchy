import { useId, useRef, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { avatarColor, avatarInitial } from "../lib/avatar";
import { ApiError } from "../lib/api";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { useFocusTrap } from "../hooks/useFocusTrap";

type Mode = "login" | "register";

/**
 * Header account control.
 *
 * Guests see a plain "Log in" button rather than only an avatar dropdown: sign
 * in has to stay reachable even while a nickname dialog is covering the page,
 * and a guest has no reason to guess that their own avatar hides the login
 * form. Registering is offered as the primary action because it keeps the
 * stats the guest has already accumulated.
 */
export function AccountMenu() {
  const user = useAuthStore((s) => s.user);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const logout = useAuthStore((s) => s.logout);

  const [openMode, setOpenMode] = useState<Mode | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const isRegistered = Boolean(user && !user.isAnonymous);

  return (
    <div className="account-menu">
      {isRegistered ? (
        <button
          type="button"
          className="account-chip"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span
            className="account-avatar"
            aria-hidden="true"
            style={{ backgroundColor: avatarColor(user!.username ?? "", false) }}
          >
            {avatarInitial(user!.username ?? "")}
          </span>
          <span className="account-name">{user!.username}</span>
        </button>
      ) : (
        <div className="account-guest">
          <button
            type="button"
            className="account-action account-action-primary"
            onClick={() => setOpenMode("register")}
          >
            Create account
          </button>
          <button
            type="button"
            className="account-action"
            onClick={() => setOpenMode("login")}
          >
            Log in
          </button>
        </div>
      )}

      {menuOpen && isRegistered && (
        <div className="account-dropdown" role="menu">
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setMenuOpen(false);
              await logout();
            }}
          >
            Log out
          </button>
        </div>
      )}

      {openMode && (
        <AuthDialog
          mode={openMode}
          // Pre-fill the name they are already playing under, so claiming it is
          // one click rather than a retype.
          suggestedUsername={user && user.isAnonymous ? user.displayName : ""}
          onClose={() => setOpenMode(null)}
          onSwitchMode={(next) => setOpenMode(next)}
          onSubmit={openMode === "login" ? login : register}
        />
      )}
    </div>
  );
}

export function AuthDialog({
  mode,
  suggestedUsername,
  onClose,
  onSwitchMode,
  onSubmit,
}: {
  mode: Mode;
  suggestedUsername?: string;
  onClose: () => void;
  onSwitchMode: (mode: Mode) => void;
  onSubmit: (username: string, password: string) => Promise<unknown>;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const usernameRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const [username, setUsername] = useState(suggestedUsername ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: usernameRef });

  const isRegister = mode === "register";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (isRegister) {
      const invalid = nicknameError(username);
      if (invalid) {
        setError(invalid);
        return;
      }
      if (password.length < 8) {
        setError("Password must be at least 8 characters.");
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(username.trim(), password);
      onClose();
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
          {isRegister ? "Create your account" : "Log in"}
        </h3>
        {isRegister && (
          <p className="modal-body">
            Keep your name and your stats across devices. Your games so far stay
            with you.
          </p>
        )}

        <form onSubmit={submit} className="auth-form">
          <label htmlFor={`${titleId}-username`}>Username</label>
          <input
            id={`${titleId}-username`}
            ref={usernameRef}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            maxLength={MAX_NICKNAME_LENGTH}
            inputMode="text"
            autoComplete="username"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="next"
            required
          />

          <label htmlFor={`${titleId}-password`}>Password</label>
          <input
            id={`${titleId}-password`}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={isRegister ? "new-password" : "current-password"}
            required
          />

          {error && <p className="auth-error" role="alert">{error}</p>}

          <button type="submit" className="modal-button" disabled={busy}>
            {busy ? "Please wait…" : isRegister ? "Create account" : "Log in"}
          </button>
        </form>

        <p className="auth-switch">
          {isRegister ? "Already have an account? " : "New here? "}
          <button
            type="button"
            className="auth-link"
            onClick={() => {
              setError(null);
              onSwitchMode(isRegister ? "login" : "register");
            }}
          >
            {isRegister ? "Log in" : "Create an account"}
          </button>
        </p>

        <button type="button" className="modal-dismiss" onClick={onClose}>
          Not now
        </button>
      </div>
    </div>
  );
}
