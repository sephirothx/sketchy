import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useOpenSettings } from "../hooks/useSettingsRoute";
import { useAuthStore } from "../store/authStore";
import { authSubmitter, type AuthCredentials, type AuthMode } from "../lib/authSubmit";
import { avatarInitial, identityColor } from "../lib/avatar";
import { ApiError, SecondFactorRequiredError } from "../lib/api";
import { passkeysAvailable } from "../lib/passkeys";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { MAX_EMAIL_LENGTH, emailLooksUsable } from "../lib/accountRecovery";
import { operatorEntries } from "../lib/operatorAccess";
import {
  getFocusableElements,
  useEscapeLayer,
  useFocusTrap,
} from "../hooks/useFocusTrap";
import { BugReportDialog } from "./BugReportDialog";
import { MIN_PASSWORD_LENGTH, PASSWORD_TOO_SHORT } from "../lib/passwordPolicy";
import {
  BugIcon,
  BulbIcon,
  ChevronDownIcon,
  GearIcon,
  KeyIcon,
  LeaveIcon,
  PlusIcon,
  ShieldIcon,
  UserIcon,
  ZapIcon,
} from "./icons";

function MenuItem({
  icon,
  className,
  onClick,
  children,
}: {
  icon: ReactNode;
  className?: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" role="menuitem" className={className} onClick={onClick}>
      <span className="menu-item-icon" aria-hidden="true">{icon}</span>
      {children}
    </button>
  );
}

/**
 * The single identity control.
 *
 * One chip in place of the three separate controls this replaced: the avatar
 * and name are who you are, and an unclaimed guest name carries a dot. Clicking
 * opens a menu - for guests too, since a guest has a profile and a game history
 * of their own and the chip is the only place to reach them from.
 *
 * Navigation only. The account's own rows - email, password, devices, data
 * export, deletion - live in Settings > Account, so there is one answer to
 * "where do I change that" rather than a menu and a dialog that each held
 * half of it.
 *
 * `compact` drops the name and shows the avatar alone, for the game-room header
 * where the row is deliberately nowrap and every pixel is spoken for. A guest's
 * compact menu is cut down to the entries that keep them in their seat, because
 * the only route out of a compact chip is a live game and navigating away would
 * give up the seat. It used to skip the menu entirely and open the claim dialog,
 * which was right while every guest entry navigated somewhere - reporting a bug
 * does not, and a guest mid-game is exactly who most needs it.
 */
export function AccountMenu({ compact = false }: { compact?: boolean } = {}) {
  const navigate = useNavigate();
  const isNarrow = useMediaQuery("(max-width: 720px)");
  const openSettings = useOpenSettings();
  const user = useAuthStore((s) => s.user);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);
  const logout = useAuthStore((s) => s.logout);

  const [mode, setMode] = useState<AuthMode | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bugReportOpen, setBugReportOpen] = useState(false);
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
  const pendingRole = user.pendingRole ?? null;
  const staffEntries = operatorEntries(user.role, { isAnonymous: isGuest });
  const shownName = isGuest ? user.displayName : (user.username ?? user.displayName);
  // Cut down rather than absent: a compact guest keeps the actions that do not
  // cost them their seat.
  const seatBound = isGuest && compact;

  // The same entry in both branches, fenced off by dividers on either side so
  // it never reads as one of the account actions around it. Offered to guests
  // too: the bugs nobody reports are the ones met before anyone signs up.
  const reportBugEntry = (
    <MenuItem
      icon={<BugIcon size={16} />}
      onClick={() => {
        setMenuOpen(false);
        setBugReportOpen(true);
      }}
    >
      Report a bug
    </MenuItem>
  );

  return (
    <div className="account-menu" ref={rootRef}>
      <button
        type="button"
        className={compact ? "identity-chip is-compact" : "identity-chip"}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-controls={menuOpen ? menuId : undefined}
        onClick={() =>
          setMenuOpen((open) => !open)
        }
        aria-label={
          isGuest
            ? `${shownName}. Your display name is not saved.`
            : `Signed in as ${shownName}`
        }
      >
        <span
          className={`identity-avatar avatar-player${!isGuest && user.avatarUrl ? " has-picture" : ""}`}
          aria-hidden="true"
          style={{ "--player-color": identityColor(shownName, isGuest, user.nameColor) } as CSSProperties}
        >
          {!isGuest && user.avatarUrl ? (
            <img src={user.avatarUrl} alt="" />
          ) : (
            avatarInitial(shownName)
          )}
        </span>
        {!compact && <span className="identity-name">{shownName}</span>}
        {isGuest && <span className="identity-unclaimed" aria-hidden="true" />}
        {!compact && (
          <span className="identity-chevron" aria-hidden="true">
            <ChevronDownIcon size={14} />
          </span>
        )}
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          id={menuId}
          className="account-dropdown"
          role="menu"
          aria-label="Account"
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          {/* On every device: the account lives in Settings now, so the menu
              that is about the account points there. On a phone the header
              has no room for a gear beside the wordmark and the chip, so this
              entry also carries the class the focus-restore looks for. */}
          <MenuItem
            icon={<GearIcon size={16} />}
            className={isNarrow ? "header-settings-button" : undefined}
            onClick={() => {
              setMenuOpen(false);
              openSettings();
            }}
          >
            Settings
          </MenuItem>
          {/* What is outstanding on this account, and the only reminder of it
              once the notice has been set aside: an offered role waits on a
              second factor, and the offer lapses if nobody comes back to it
              (R-AUTH-20). Gone the moment the role begins. */}
          {pendingRole && (
            <MenuItem
              icon={<ShieldIcon size={16} />}
              onClick={() => {
                setMenuOpen(false);
                openSettings("account");
              }}
            >
              Finish your {pendingRole === "admin" ? "administrator" : "moderator"} role
            </MenuItem>
          )}
          {/* The two entries that leave the page. Hidden for a guest in a
              live game, where following one would give up their seat. */}
          {!seatBound && (
            <>
              <MenuItem
                icon={<UserIcon size={16} />}
                onClick={() => {
                  setMenuOpen(false);
                  navigate("/profile");
                }}
              >
                My profile
              </MenuItem>
              <MenuItem
                icon={<ZapIcon size={16} />}
                onClick={() => {
                  setMenuOpen(false);
                  navigate("/prompt-lists");
                }}
              >
                Prompt stats
              </MenuItem>
            </>
          )}
          {isGuest ? (
            <>
              <div className="account-menu-divider" role="presentation" />
              {reportBugEntry}
              <div className="account-menu-divider" role="presentation" />
              <MenuItem
                icon={<PlusIcon size={16} />}
                onClick={() => {
                  setMenuOpen(false);
                  setMode("claim");
                }}
              >
                Create account
              </MenuItem>
              <MenuItem
                icon={<KeyIcon size={16} />}
                onClick={() => {
                  setMenuOpen(false);
                  setMode("login");
                }}
              >
                Log in
              </MenuItem>
            </>
          ) : (
            <>
              <MenuItem
                icon={<BulbIcon size={16} />}
                onClick={() => {
                  setMenuOpen(false);
                  navigate("/my-prompt-lists");
                }}
              >
                My prompt lists
              </MenuItem>
              {/* Shown, not enforced: each of these endpoints checks the role
                  again for itself and answers 404 to anyone else. Hiding them
                  is about not offering a door that will not open. */}
              {staffEntries.map((entry) => (
                <MenuItem
                  key={entry.path}
                  icon={<ShieldIcon size={16} />}
                  className="account-staff-entry"
                  onClick={() => {
                    setMenuOpen(false);
                    navigate(entry.path);
                  }}
                >
                  {entry.label}
                </MenuItem>
              ))}
              <div className="account-menu-divider" role="presentation" />
              {reportBugEntry}
              <div className="account-menu-divider" role="presentation" />
              <MenuItem
                icon={<LeaveIcon size={16} />}
                className="menu-item-danger"
                onClick={() => {
                  setMenuOpen(false);
                  void logout();
                }}
              >
                Log out
              </MenuItem>
            </>
          )}
        </div>
      )}

      {mode && (
        <AuthDialog
          mode={mode}
          suggestedUsername={isGuest ? user.displayName : ""}
          onClose={() => setMode(null)}
          onSwitchMode={setMode}
          onSubmit={authSubmitter(mode, login, register)}
        />
      )}
      {bugReportOpen && (
        <BugReportDialog onClose={() => setBugReportOpen(false)} />
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
  /** One object rather than four positions. `login` and `register` take
      different arguments in a different order, and a function of three
      parameters is assignable to a type of four - so passing one where the
      other was expected type-checks perfectly and silently drops whatever
      came last. That is how the second factor stopped being sent: the code
      went into `login`'s third parameter, which is not `code`. */
  onSubmit: (credentials: AuthCredentials) => Promise<unknown>;
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const usernameRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  const [username, setUsername] = useState(suggestedUsername ?? "");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Revealed only once the server has said it wants one, so the field does not
  // appear for the overwhelming majority of accounts that hold no second
  // factor - and so this form never has to guess which accounts are staff.
  const [code, setCode] = useState("");
  const [codeWanted, setCodeWanted] = useState(false);
  // Offered from the start on a browser that can do it, because a passkey
  // sign-in needs neither of the fields below (R-AUTH-23) - and forced when
  // the server says the account has no code to type.
  const [passkeyOnly, setPasskeyOnly] = useState(false);
  const canUsePasskeys = passkeysAvailable();

  // Both of these are answers about one account and one attempt. Switching
  // between signing in and creating an account starts a different one, and
  // `passkeyOnly` left standing hides the form on a screen that offers no
  // passkey button either - a dialog with nothing in it at all.
  useEffect(() => {
    setPasskeyOnly(false);
    setCodeWanted(false);
    setError(null);
  }, [mode]);

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
      if (password.length < MIN_PASSWORD_LENGTH) {
        setError(PASSWORD_TOO_SHORT);
        return;
      }
      // Optional, so an empty field is fine; a filled-in one that cannot work
      // is worth catching before the account is created around it.
      if (email.trim() && !emailLooksUsable(email)) {
        setError("That does not look like an email address.");
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
        code: code.trim() || undefined,
      });
      onClose();
    } catch (submitError) {
      if (submitError instanceof SecondFactorRequiredError) {
        // Not a failure to report as one: the password was right and the
        // account wants its second factor. Which one decides what to show -
        // a field for a code, or the passkey button and no field at all.
        if (submitError.kind === "passkey") setPasskeyOnly(true);
        else setCodeWanted(true);
      }
      setError(
        submitError instanceof ApiError
          ? submitError.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function signInWithPasskey() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // Through the store, which does what a password sign-in does after its
      // own proof: gives up the guest's seat, adopts the account and bounces
      // the socket onto it. Setting the user alone left the socket playing as
      // somebody this browser had stopped being.
      await useAuthStore.getState().signInWithPasskey();
      onClose();
    } catch (passkeyError) {
      setError(
        passkeyError instanceof DOMException
          ? "No passkey was used. You can sign in with your password instead."
          : passkeyError instanceof ApiError
            ? passkeyError.message
            : "That passkey was not accepted.",
      );
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
          {isClaim ? "Create your account" : "Log in"}
        </h3>
        {isClaim && (
          <p className="modal-body">
            {suggestedUsername
              ? `Create an account to keep ${suggestedUsername} as your username and save your stats on every device.`
              : "Keep your username and your stats on every device."}
          </p>
        )}

        {/* Signing in, not claiming: a passkey belongs to an account that
            already exists. Above the fields because it is the shorter route
            for the accounts that hold one, and because a staff account may
            have nothing else to offer. */}
        {!isClaim && canUsePasskeys && (
          <>
            <button
              type="button"
              className="modal-button auth-passkey"
              onClick={() => void signInWithPasskey()}
              disabled={busy}
            >
              {busy ? "Waiting for your device…" : "Sign in with a passkey"}
            </button>
            {passkeyOnly ? (
              <p className="modal-hint">
                This account signs in with a passkey.
              </p>
            ) : (
              <p className="auth-divider"><span>or</span></p>
            )}
          </>
        )}
        {/* Not `hidden`: that attribute is a user-agent default, and
            `.auth-form { display: flex }` beats it - the form stayed on
            screen inviting a second attempt at a password route the server
            has just said cannot finish. Rendering the decision leaves no
            room for a stylesheet to disagree with it. The two links below
            sit outside the form, so the way on is still there. */}
        {!(passkeyOnly && !isClaim) && (
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

          {codeWanted && (
            <>
              <label htmlFor={`${titleId}-code`}>
                Code from your authenticator app
              </label>
              <input
                id={`${titleId}-code`}
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                  setError(null);
                }}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={64}
                autoFocus
                required
              />
              <p className="modal-hint">
                A recovery code works here too, and can be used once.
              </p>
            </>
          )}

          {isClaim && (
            <>
              <label htmlFor={`${titleId}-email`}>
                Email <span className="auth-optional">optional</span>
              </label>
              {/* The only way back into an account whose password is lost. Not
                  required, because a deployment with no mail server would then
                  be one nobody could register on at all. */}
              <input
                id={`${titleId}-email`}
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
              />
              <p className="auth-hint">
                Lets you reset your password later. Used for nothing else.
              </p>
            </>
          )}

          {error && <p className="auth-error" role="alert">{error}</p>}

          <button type="submit" className="modal-button" disabled={busy}>
            {busy ? "Please wait…" : isClaim ? "Create account" : "Log in"}
          </button>
        </form>
        )}

        {!isClaim && (
          <p className="auth-switch">
            <Link className="auth-link" to="/forgot-password" onClick={onClose}>
              Forgot your password?
            </Link>
          </p>
        )}

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
