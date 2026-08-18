import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { GUEST_NAME_COLOR } from "./ColoredPlayerName";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { initialsFromName } from "../lib/avatar";
import { emitWithAck } from "../lib/socket";
import { suggestUsername } from "../lib/username";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";

const MIN_PASSWORD_LENGTH = 6;

export function AccountMenu() {
  const user = useAuthStore((state) => state.user);
  const isLoading = useAuthStore((state) => state.isLoading);
  const error = useAuthStore((state) => state.error);
  const dialog = useAuthStore((state) => state.dialog);
  const openDialog = useAuthStore((state) => state.openDialog);
  const closeDialog = useAuthStore((state) => state.closeDialog);
  const register = useAuthStore((state) => state.register);
  const login = useAuthStore((state) => state.login);
  const logout = useAuthStore((state) => state.logout);
  const nickname = useGameStore((state) => state.nickname);
  const roomId = useGameStore((state) => state.roomId);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const clearSession = useGameStore((state) => state.clearSession);
  const reset = useGameStore((state) => state.reset);
  const navigate = useNavigate();

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const displayName = user?.isAnonymous
    ? (nickname.trim() || user.displayName || "Guest")
    : (user?.username || user?.displayName || "Player");
  const suggested = suggestUsername(nickname.trim() || user?.displayName || "");
  const avatarColor = user?.isAnonymous
    ? GUEST_NAME_COLOR
    : (nameColor || user?.nameColor || GUEST_NAME_COLOR);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || buttonRef.current?.contains(target)) return;
      setMenuOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [menuOpen]);

  async function handleLogout() {
    setMenuOpen(false);
    if (roomId) {
      try {
        await emitWithAck("leave_room", {});
      } catch {
        // Continue logging out even if leave fails.
      }
      clearSession();
      reset();
      navigate("/");
    }
    await logout();
  }

  const authDialogs = (
    <>
      {dialog === "register" && (
        <AuthFormDialog
          mode="register"
          defaultUsername={suggested}
          error={error}
          busy={isLoading}
          claimName={suggested}
          onClose={closeDialog}
          onSubmit={register}
          onSwitch={() => openDialog("login")}
        />
      )}
      {dialog === "login" && (
        <AuthFormDialog
          mode="login"
          defaultUsername=""
          error={error}
          busy={isLoading}
          onClose={closeDialog}
          onSubmit={login}
          onSwitch={() => openDialog("register")}
        />
      )}
    </>
  );

  if (!user) {
    return (
      <div className="account-menu">
        <button
          type="button"
          className="account-menu-button"
          onClick={() => openDialog("login")}
          aria-label="Log in"
        >
          <span className="account-menu-avatar" aria-hidden="true" />
          <span className="header-action-label">Log in</span>
        </button>
        {authDialogs}
      </div>
    );
  }

  return (
    <div className="account-menu">
      <button
        ref={buttonRef}
        type="button"
        className="account-menu-button"
        onClick={() => {
          if (user.isAnonymous) {
            openDialog("login");
            return;
          }
          setMenuOpen((open) => !open);
        }}
        aria-haspopup={user.isAnonymous ? undefined : "true"}
        aria-expanded={user.isAnonymous ? undefined : menuOpen}
        aria-controls={!user.isAnonymous && menuOpen ? "account-menu-dropdown" : undefined}
        aria-label={user.isAnonymous ? "Log in" : `Account: ${displayName}`}
        title={displayName}
      >
        <LetterAvatar name={displayName} color={avatarColor} />
        {user.isAnonymous ? <span className="header-action-label">Log in</span> : null}
      </button>
      {menuOpen && !user.isAnonymous && (
        <div id="account-menu-dropdown" ref={menuRef} className="account-menu-dropdown">
          <div className="account-menu-profile">
            <LetterAvatar name={displayName} color={avatarColor} large />
            <div>
              <strong>{displayName}</strong>
              <p>@{user.username}</p>
            </div>
          </div>
          <button type="button" onClick={() => void handleLogout()}>
            Log out
          </button>
        </div>
      )}
      {authDialogs}
    </div>
  );
}

function LetterAvatar({
  name,
  color,
  large = false,
}: {
  name: string;
  color: string;
  large?: boolean;
}) {
  return (
    <span
      className={large ? "account-menu-avatar account-menu-avatar-lg" : "account-menu-avatar"}
      style={{ backgroundColor: color }}
      aria-hidden="true"
    >
      {initialsFromName(name)}
    </span>
  );
}

function AuthFormDialog({
  mode,
  defaultUsername,
  error,
  busy,
  claimName,
  onClose,
  onSubmit,
  onSwitch,
}: {
  mode: "register" | "login";
  defaultUsername: string;
  error: string | null;
  busy: boolean;
  claimName?: string;
  onClose: () => void;
  onSubmit: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  onSwitch: () => void;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const [username, setUsername] = useState(defaultUsername);
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useFocusTrap(dialogRef, {
    onEscape: onClose,
    initialFocusRef: firstFieldRef,
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (username.trim().length < 3) {
      setLocalError("Username must be at least 3 characters.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setLocalError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setLocalError(null);
    await onSubmit(username.trim(), password);
  }

  const title = mode === "register" ? "Create account" : "Log in";
  const switchLabel = mode === "register" ? "Already have an account? Log in" : "Need an account? Create one";

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card account-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">{title}</h3>
        {mode === "register" && (
          <p className="account-dialog-copy">
            {claimName
              ? `${claimName} is available — claim it to keep this name and your stats on any device.`
              : "Create an account to keep your stats on any device."}
          </p>
        )}
        <form className="account-dialog-form" onSubmit={(event) => void handleSubmit(event)}>
          <label>
            Username
            <input
              ref={firstFieldRef}
              type="text"
              autoComplete={mode === "login" ? "username" : "off"}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              maxLength={32}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={MIN_PASSWORD_LENGTH}
              maxLength={128}
              required
            />
          </label>
          {(localError || error) && (
            <p className="invite-form-error" role="alert">{localError || error}</p>
          )}
          <div className="account-dialog-actions">
            <button type="submit" className="modal-button" disabled={busy}>
              {busy ? "Please wait…" : title}
            </button>
            <button type="button" className="account-dialog-secondary" onClick={onClose} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
        <button type="button" className="account-dialog-switch" onClick={onSwitch}>
          {switchLabel}
        </button>
      </div>
    </div>
  );
}
