import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { avatarInitial, identityColor } from "../lib/avatar";
import { ApiError } from "../lib/api";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import {
  getFocusableElements,
  useEscapeLayer,
  useFocusTrap,
} from "../hooks/useFocusTrap";

export type AuthMode = "claim" | "login";

/**
 * The single identity control.
 *
 * One chip in place of the three separate controls this replaced: the avatar
 * and name are who you are, and an unclaimed guest name carries a dot. Clicking
 * opens a menu - for guests too, since a guest has a profile and a game history
 * of their own and the chip is the only place to reach them from.
 *
 * `compact` drops the name and shows the avatar alone, for the game-room header
 * where the row is deliberately nowrap and every pixel is spoken for. It also
 * keeps the guest chip going straight to the claim dialog: the only route out
 * of a compact chip is a live game, and navigating away would give up the seat.
 */
export function AccountMenu({ compact = false }: { compact?: boolean } = {}) {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const logout = useAuthStore((s) => s.logout);

  const [mode, setMode] = useState<AuthMode | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

  useEscapeLayer(menuOpen, () => setMenuOpen(false));
  // Menu semantics come with menu behaviour: declaring role="menu" without it
  // tells a screen reader to expect navigation that does not exist. The trap
  // keeps Tab inside, moves focus to the first item on open, and returns it to
  // the chip on close; the arrow keys are handled below.
  useFocusTrap(menuRef, { active: menuOpen });

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(currentIndex + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  // A menu is dismissed by looking away from it. The chip itself is inside the
  // root, so clicking it still toggles rather than closing and reopening.
  useEffect(() => {
    if (!menuOpen) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [menuOpen]);

  // Before identity resolves, and during a first run, there is no one to show.
  if (!user || (user.isAnonymous && !user.displayName)) return null;

  const isGuest = user.isAnonymous;
  const shownName = isGuest ? user.displayName : (user.username ?? user.displayName);
  const opensDialogDirectly = isGuest && compact;

  return (
    <div className="account-menu" ref={rootRef}>
      <button
        type="button"
        className={compact ? "identity-chip is-compact" : "identity-chip"}
        aria-haspopup={opensDialogDirectly ? "dialog" : "menu"}
        aria-expanded={opensDialogDirectly ? undefined : menuOpen}
        aria-controls={opensDialogDirectly || !menuOpen ? undefined : menuId}
        onClick={() =>
          opensDialogDirectly ? setMode("claim") : setMenuOpen((open) => !open)
        }
        aria-label={
          isGuest
            ? `${shownName}. Your name is not saved.`
            : `Signed in as ${shownName}`
        }
      >
        <span
          className="identity-avatar"
          aria-hidden="true"
          style={{ backgroundColor: identityColor(shownName, isGuest, user.nameColor) }}
        >
          {avatarInitial(shownName)}
        </span>
        {!compact && <span className="identity-name">{shownName}</span>}
        {isGuest && <span className="identity-unclaimed" aria-hidden="true" />}
      </button>

      {menuOpen && !opensDialogDirectly && (
        <div
          ref={menuRef}
          id={menuId}
          className="account-dropdown"
          role="menu"
          aria-label="Account"
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              navigate("/profile");
            }}
          >
            My profile
          </button>
          {isGuest ? (
            <>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setMode("claim");
                }}
              >
                Claim your name
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  setMode("login");
                }}
              >
                Log in
              </button>
            </>
          ) : (
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
          )}
        </div>
      )}

      {mode && (
        <AuthDialog
          mode={mode}
          suggestedUsername={isGuest ? user.displayName : ""}
          onClose={() => setMode(null)}
          onSwitchMode={setMode}
          onSubmit={mode === "login" ? login : register}
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
  mode: AuthMode;
  suggestedUsername?: string;
  onClose: () => void;
  onSwitchMode: (mode: AuthMode) => void;
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
  const isClaim = mode === "claim";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (isClaim) {
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
          {isClaim
            ? suggestedUsername
              ? `Claim ${suggestedUsername}`
              : "Create your account"
            : "Log in"}
        </h3>
        {isClaim && (
          <p className="modal-body">
            {suggestedUsername
              ? "Your name isn’t saved yet. Claim it so nobody else can take it, and keep it on every device."
              : "Keep your name and your stats on every device."}
          </p>
        )}

        <form onSubmit={submit} className="auth-form">
          <label htmlFor={`${titleId}-username`}>Username</label>
          {/* Pre-filled from the guest name but editable: this is where a typo
              gets fixed, and where you pick another if yours is taken. */}
          <input
            id={`${titleId}-username`}
            ref={usernameRef}
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              setError(null);
            }}
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
            onChange={(event) => {
              setPassword(event.target.value);
              setError(null);
            }}
            autoComplete={isClaim ? "new-password" : "current-password"}
            required
          />

          {error && <p className="auth-error" role="alert">{error}</p>}

          <button type="submit" className="modal-button" disabled={busy}>
            {busy
              ? "Please wait…"
              : isClaim
                ? // Mirrors the title: there is a name to claim only when one
                  // was carried in, and otherwise this is a plain sign-up.
                  suggestedUsername
                  ? "Claim my name"
                  : "Create"
                : "Log in"}
          </button>
        </form>

        <p className="auth-switch">
          {isClaim ? "Already registered? " : "New here? "}
          <button
            type="button"
            className="auth-link"
            onClick={() => {
              setError(null);
              onSwitchMode(isClaim ? "login" : "claim");
            }}
          >
            {isClaim ? "Log in" : "Create an account"}
          </button>
        </p>

        <button type="button" className="modal-dismiss" onClick={onClose}>
          Not now
        </button>
      </div>
    </div>
  );
}
