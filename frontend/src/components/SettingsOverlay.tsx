import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { emitWithAck, socket } from "../lib/socket";
import { ApiError } from "../lib/api";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { flushSettingsSync, onSettingsSyncError, queueSettingsSync } from "../lib/accountSettingsSync";
import { maskEmail, readEmailState, type EmailState } from "../lib/accountRecovery";
import { chooseDoodle, removeAvatar, uploadAvatar } from "../lib/avatars";
import type { Doodle } from "../lib/avatarDoodles";
import { useToast } from "../lib/toast";
import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  SETTINGS_SECTIONS,
  sectionFromPath,
  settingsPath,
  type SettingsLocationState,
  type SettingsSection,
} from "../hooks/useSettingsRoute";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import { AddEmailDialog } from "./AddEmailDialog";
import { SessionManagerDialog } from "./SessionManagerDialog";
import { AccountDataDialog } from "./AccountDataDialog";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { PictureCropDialog } from "./PictureCropDialog";
import { AvatarDoodleDialog } from "./AvatarDoodleDialog";
import { DeleteAccountDialog } from "./DeleteAccountDialog";
import { SegmentedControl } from "./RoomSetupControls";
import { Avatar } from "./ui/Avatar";
import {
  ACTION_LABELS,
  DEFAULT_KEY_BINDINGS,
  NAME_COLOR_PALETTE,
  getSystemTheme,
  useSettingsStore,
  type AppTheme,
  type BrushCursorStyle,
  type KeyBindings,
  type TimeFormat,
} from "../store/settingsStore";
import {
  BrushIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CircleIcon,
  ClockIcon,
  DevicesIcon,
  DownloadIcon,
  EraserIcon,
  EyeIcon,
  EyeOffIcon,
  FillIcon,
  GearIcon,
  ImageIcon,
  KeyIcon,
  KeyboardIcon,
  LockIcon,
  MailIcon,
  PencilIcon,
  PlusIcon,
  RectIcon,
  SunIcon,
  TrashIcon,
  TriangleIcon,
  UndoIcon,
  UserIcon,
  VolumeIcon,
  XIcon,
} from "./icons";

/* ------------------------------------------------------------- vocabulary */

const SECTION_LABELS: Record<SettingsSection, string> = {
  account: "Account",
  appearance: "Appearance",
  sound: "Sound & effects",
  shortcuts: "Shortcuts",
};

const SECTION_ICONS: Record<SettingsSection, ReactNode> = {
  account: <UserIcon size={16} />,
  appearance: <SunIcon size={16} />,
  sound: <VolumeIcon size={16} />,
  shortcuts: <KeyboardIcon size={16} />,
};

/** The palette, with a name a screen reader can say instead of a hex. */
const NAME_COLOR_NAMES: Record<(typeof NAME_COLOR_PALETTE)[number], string> = {
  "#e11d48": "Red",
  "#f97316": "Orange",
  "#eab308": "Yellow",
  "#84cc16": "Lime",
  "#16a34a": "Green",
  "#0d9488": "Teal",
  "#38bdf8": "Sky",
  "#2563eb": "Blue",
  "#6366f1": "Indigo",
  "#a855f7": "Purple",
  "#d946ef": "Magenta",
  "#f472b6": "Pink",
  "#a0522d": "Brown",
};

const ACTION_ICONS: Record<keyof KeyBindings, ReactNode> = {
  brush: <BrushIcon size={15} />,
  fill: <FillIcon size={15} />,
  eraser: <EraserIcon size={15} />,
  rectangle: <RectIcon size={15} />,
  triangle: <TriangleIcon size={15} />,
  ellipse: <CircleIcon size={15} />,
  brushDecrease: <ChevronDownIcon size={15} />,
  brushIncrease: <ChevronUpIcon size={15} />,
  undo: <UndoIcon size={15} />,
};

const THEME_OPTIONS: { value: AppTheme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

const TIME_FORMAT_OPTIONS: { value: TimeFormat; label: string }[] = [
  { value: "system", label: "System" },
  { value: "12h", label: "12-hour" },
  { value: "24h", label: "24-hour" },
];

const BRUSH_CURSOR_OPTIONS: { value: BrushCursorStyle; label: string }[] = [
  { value: "crosshair", label: "Crosshair" },
  { value: "circle", label: "Outline" },
];

function formatKey(key: string): string {
  if (key === " ") return "Space";
  if (key.length === 1) return key.toUpperCase();
  return key.charAt(0).toUpperCase() + key.slice(1);
}

/* ------------------------------------------------------------- primitives */

/**
 * One preference: what it is and why on the left, the control on the right.
 * `stacked` gives a wide control - a palette, theme cards - the whole width.
 */
function Row({
  label,
  hint,
  children,
  stacked = false,
  tone,
  locked = false,
}: {
  label: string;
  hint?: ReactNode;
  children?: ReactNode;
  stacked?: boolean;
  tone?: "danger";
  locked?: boolean;
}) {
  const classes = ["settings-row"];
  if (stacked) classes.push("is-stacked");
  if (tone) classes.push(`is-${tone}`);
  if (locked) classes.push("settings-locked");
  return (
    <div className={classes.join(" ")}>
      <span className="settings-row-label">
        <b>{label}</b>
        {hint && <small>{hint}</small>}
      </span>
      <span className="settings-row-control">{children}</span>
    </div>
  );
}

/**
 * An on/off row. The room form's switch draws the track; this row keeps
 * label-then-control with the reason in plain sight rather than behind a "?".
 */
function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="settings-row settings-toggle-row">
      <span className="settings-row-label">
        <b>{label}</b>
        {hint && <small>{hint}</small>}
      </span>
      <span className="settings-row-control">
        <input
          type="checkbox"
          role="switch"
          className="settings-toggle-input"
          checked={checked}
          aria-label={label}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="m3-switch-track" aria-hidden="true">
          <span className="m3-switch-thumb" />
        </span>
      </span>
    </label>
  );
}

function Group({
  title,
  hint,
  action,
  children,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="settings-group">
      <div className="settings-group-head">
        <h4>{title}</h4>
        {action}
      </div>
      {hint && <p className="settings-group-hint">{hint}</p>}
      {children}
    </section>
  );
}

/** What an account-only row says instead of offering a control that cannot work. */
function NeedsAccount() {
  return (
    <span className="settings-locked-reason">
      <LockIcon size={13} />
      Needs an account
    </span>
  );
}

/* ---------------------------------------------------------------- account */

/**
 * The address, and where it stands (R-SET-08).
 *
 * Printed with its middle removed, because Settings gets opened in rooms with
 * other people looking at the screen and the address is the one value here
 * worth copying down. A reveal control shows it in full for somebody who
 * needs to read it back. The state is a symbol as well as a word, because
 * whether it is verified decides whether the account can be recovered at all.
 */
function EmailAddressStatus({
  address,
  verified,
}: {
  address: string;
  verified: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <span className="settings-email-line">
      <span className="settings-email" data-revealed={revealed || undefined}>
        {revealed ? address : maskEmail(address)}
      </span>
      <button
        type="button"
        className="settings-email-reveal"
        aria-pressed={revealed}
        aria-label={revealed ? "Hide the full address" : "Show the full address"}
        title={revealed ? "Hide" : "Show in full"}
        onClick={() => setRevealed((shown) => !shown)}
      >
        {revealed ? <EyeOffIcon size={14} /> : <EyeIcon size={14} />}
      </button>
      <span className={`settings-email-status ${verified ? "is-verified" : "is-unverified"}`}>
        {verified ? <CheckIcon size={12} /> : <ClockIcon size={12} />}
        {verified ? "Verified" : "Not verified"}
      </span>
    </span>
  );
}

/**
 * The pencil on the disc's corner opens a menu: a doodle of ours, a picture
 * of the player's own, and - once there is either - taking it off. A real
 * menu: Escape, outside click and the arrow keys all work, the way the
 * account menu's do.
 */
function PictureEditChip({
  hasPicture,
  busy,
  onChoose,
  onPickDoodle,
  onRemove,
}: {
  hasPicture: boolean;
  busy: boolean;
  onChoose: (file: File | undefined) => void;
  onPickDoodle: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const menuId = useId();

  useEscapeLayer(open, () => setOpen(false));
  useFocusTrap(menuRef, { active: open });

  useEffect(() => {
    if (!open) return;
    function closeOnOutsideClick(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    }
  }

  function pick() {
    setOpen(false);
    inputRef.current?.click();
  }

  return (
    <div className="settings-you-edit" ref={rootRef}>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="settings-picture-input"
        aria-label="Choose a picture"
        onChange={(event) => {
          onChoose(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        className="settings-you-edit-chip"
        disabled={busy}
        aria-label="Edit picture"
        title="Edit picture"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((shown) => !shown)}
      >
        <PencilIcon size={14} />
      </button>
      {open && (
        <div
          ref={menuRef}
          id={menuId}
          className="settings-you-menu"
          role="menu"
          aria-label="Picture"
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onPickDoodle();
            }}
          >
            <BrushIcon size={15} />
            Pick a doodle
          </button>
          <button type="button" role="menuitem" onClick={pick}>
            <ImageIcon size={15} />
            Upload a picture
          </button>
          {hasPicture && (
            <button
              type="button"
              role="menuitem"
              className="is-danger"
              onClick={() => {
                setOpen(false);
                onRemove();
              }}
            >
              <TrashIcon size={15} />
              Remove
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function AccountPane({ signedInHere }: { signedInHere: boolean }) {
  const user = useAuthStore((state) => state.user);
  const setDisplayName = useAuthStore((state) => state.setDisplayName);
  const setAccountNameColor = useAuthStore((state) => state.setNameColor);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const isGuest = Boolean(user?.isAnonymous);
  const activePlayerId = useGameStore((state) => state.playerId);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const setLocalNameColor = useSettingsStore((state) => state.setNameColor);

  const [draftName, setDraftName] = useState(user?.displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [pictureBusy, setPictureBusy] = useState(false);
  const [pictureError, setPictureError] = useState<string | null>(null);
  // A chosen file opens the crop dialog; the dialog uploads what was framed.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [doodlesOpen, setDoodlesOpen] = useState(false);
  const [editingName, setEditingName] = useState(false);

  async function wearDoodle(doodle: Doodle) {
    await chooseDoodle(doodle);
    await useAuthStore.getState().fetchMe();
    setDoodlesOpen(false);
    setPictureError(null);
  }

  async function usePicture(base64: string) {
    // The dialog shows the server's reason - "too large", "a moderator
    // removed your picture" - itself, and stays open for another try.
    await uploadAvatar(base64);
    await useAuthStore.getState().fetchMe();
    setPendingFile(null);
    setPictureError(null);
  }

  async function dropPicture() {
    if (pictureBusy) return;
    setPictureBusy(true);
    setPictureError(null);
    try {
      await removeAvatar();
      await useAuthStore.getState().fetchMe();
    } catch (error) {
      setPictureError(
        error instanceof ApiError ? error.message : "Could not remove the picture.",
      );
    } finally {
      setPictureBusy(false);
    }
  }
  const [nameBusy, setNameBusy] = useState(false);
  // Arriving straight at /settings/account beats `GET /api/auth/me`, so the
  // field would otherwise start empty and stay empty. It follows the account's
  // own name whenever that changes - including turning up - and leaves typing
  // alone otherwise.
  const knownName = useRef(user?.displayName ?? "");
  useEffect(() => {
    const current = user?.displayName ?? "";
    if (current !== knownName.current) {
      knownName.current = current;
      setDraftName(current);
    }
  }, [user?.displayName]);

  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [emailOpen, setEmailOpen] = useState(false);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [dataOpen, setDataOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [email, setEmail] = useState<EmailState | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(signedInHere);

  useEffect(() => {
    if (isGuest) return;
    let active = true;
    void readEmailState()
      .then((state) => {
        if (active) setEmail(state);
      })
      .catch(() => {
        // The row falls back to offering the dialog, which asks for itself.
      });
    return () => {
      active = false;
    };
  }, [isGuest, emailOpen]);

  async function saveDisplayName() {
    const trimmed = draftName.trim();
    if (nameBusy || trimmed === (user?.displayName ?? "")) return;
    const invalid = nicknameError(trimmed);
    if (invalid) {
      setNameError(invalid);
      return;
    }
    setNameBusy(true);
    setNameError(null);
    try {
      // In a room the socket owns the change, so the seat and the other
      // players follow it; outside one, writing the account is enough.
      if (activePlayerId) {
        const response = await emitWithAck<{ ok: boolean; error?: string }>(
          "rename_player",
          { nickname: trimmed },
        );
        if (!response.ok) {
          setNameError(response.error || "Could not change your display name.");
          return;
        }
        await useAuthStore.getState().fetchMe();
      } else {
        await setDisplayName(trimmed);
      }
      setEditingName(false);
    } catch (error) {
      // The server's reason - "that name belongs to a registered player" is
      // the whole point of the check, and a generic line would leave the
      // player guessing why it was refused.
      setNameError(
        error instanceof ApiError
          ? error.message
          : "Could not change your display name. Please try again.",
      );
    } finally {
      setNameBusy(false);
    }
  }

  function chooseNameColor(next: string) {
    setLocalNameColor(next);
    if (isGuest) return;
    // The socket recolors the room the player is in right now; the account
    // write is what makes the choice outlast it. Neither failing is worth an
    // error over a color: it already applies here.
    if (activePlayerId) {
      socket.emit("update_player_settings", { nameColor: next });
    }
    void setAccountNameColor(next).catch(() => {});
  }

  // What the email row is about: a pending address is the one the player is
  // waiting on even while a verified one is still in place.
  const shownAddress = email?.pendingAddress ?? email?.address ?? null;
  const shownVerified = Boolean(shownAddress && !email?.pendingAddress && email?.verified);

  return (
    <>
      {noticeOpen && (
        <div className="settings-notice" role="status">
          <CheckIcon size={16} />
          <p>
            <b>These are {user?.username}’s settings now.</b> The theme, sound and
            shortcuts came from the account. What this browser had is untouched, and
            comes back if you log out.
          </p>
          <button type="button" aria-label="Dismiss" onClick={() => setNoticeOpen(false)}>
            <XIcon size={14} />
          </button>
        </div>
      )}

      {isGuest && (
        <div className="settings-guest-card">
          <b>Playing as a guest</b>
          <p>
            {user?.displayName} lives in this browser only. An account keeps the name,
            your points and your history on every device, and lets you pick a color.
          </p>
          <div className="settings-guest-actions">
            <button type="button" className="btn btn-primary" onClick={() => setAuthMode("claim")}>
              <PlusIcon size={15} />
              Create an account
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setAuthMode("login")}>
              <KeyIcon size={15} />
              Log in
            </button>
          </div>
        </div>
      )}

      <Group title="You">
        {/* The identity card: disc, name in its color, palette. A registered
            player always plays as their username (R-ACCT-05), so only a guest
            gets a way to change the name; and only an account gets a picture
            or a color, because the grey initial is what marks a guest. */}
        <div className="settings-you">
          <div className="settings-you-disc">
            <Avatar
              name={user?.displayName ?? ""}
              nameColor={isGuest ? undefined : nameColor}
              avatarUrl={user?.avatarUrl}
              isAnonymous={isGuest}
              size={96}
            />
            {!isGuest && (
              <PictureEditChip
                hasPicture={Boolean(user?.avatarUrl)}
                busy={pictureBusy}
                onChoose={(file) => {
                  if (file) setPendingFile(file);
                }}
                onPickDoodle={() => setDoodlesOpen(true)}
                onRemove={() => void dropPicture()}
              />
            )}
          </div>
          <div className="settings-you-body">
            <div className="settings-you-name-line">
              {isGuest && editingName ? (
                <>
                  <input
                    id="settings-display-name"
                    type="search"
                    inputMode="text"
                    value={draftName}
                    autoFocus
                    onChange={(event) => {
                      setDraftName(event.target.value);
                      setNameError(null);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void saveDisplayName();
                    }}
                    maxLength={MAX_NICKNAME_LENGTH}
                    autoComplete="nickname"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    aria-label="Display name"
                    aria-describedby={nameError ? "settings-name-error" : undefined}
                  />
                  {/* The one thing here the server can refuse - the name may
                      belong to a registered player - so it keeps a button
                      where everything else applies at once (R-SET-05). */}
                  <button
                    type="button"
                    className="btn btn-primary btn-compact"
                    disabled={nameBusy || draftName.trim() === (user?.displayName ?? "")}
                    onClick={() => void saveDisplayName()}
                  >
                    {nameBusy ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    disabled={nameBusy}
                    onClick={() => {
                      setEditingName(false);
                      setNameError(null);
                      setDraftName(user?.displayName ?? "");
                    }}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <strong
                    className={`settings-you-name colored-player-name${isGuest ? " is-guest" : ""}`}
                    style={isGuest ? undefined : { color: nameColor }}
                  >
                    {user?.displayName}
                  </strong>
                  {isGuest && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-compact"
                      onClick={() => setEditingName(true)}
                    >
                      <PencilIcon size={14} />
                      Change
                    </button>
                  )}
                </>
              )}
            </div>
            {nameError && (
              <p id="settings-name-error" className="auth-error" role="alert">
                {nameError}
              </p>
            )}
            {!isGuest && (
              <span className="settings-swatches" role="group" aria-label="Name color">
                {NAME_COLOR_PALETTE.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className={`settings-swatch${color === nameColor ? " is-selected" : ""}`}
                    style={{ background: color }}
                    aria-label={NAME_COLOR_NAMES[color]}
                    aria-pressed={color === nameColor}
                    title={NAME_COLOR_NAMES[color]}
                    onClick={() => chooseNameColor(color)}
                  >
                    {color === nameColor && <CheckIcon size={14} />}
                  </button>
                ))}
              </span>
            )}
            {pictureError && (
              <p className="auth-error" role="alert">
                {pictureError}
              </p>
            )}
          </div>
        </div>
      </Group>

      <Group title="Signing in">
        <Row
          label="Email"
          locked={isGuest}
          hint={
            isGuest ? (
              "A guest has nothing to recover: there is no password to forget."
            ) : shownAddress ? (
              <EmailAddressStatus address={shownAddress} verified={shownVerified} />
            ) : (
              "Without one there is no way back into this account if the password is forgotten."
            )
          }
        >
          {isGuest ? (
            <NeedsAccount />
          ) : (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => setEmailOpen(true)}
            >
              <MailIcon size={15} />
              {shownAddress ? "Change" : "Add an email"}
            </button>
          )}
        </Row>
        <Row
          label="Password"
          locked={isGuest}
          hint={
            isGuest ? "Guests have no password." : "Changing it signs every other device out."
          }
        >
          {isGuest ? (
            <NeedsAccount />
          ) : (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => setPasswordOpen(true)}
            >
              <KeyIcon size={15} />
              Change password
            </button>
          )}
        </Row>
        <Row
          label="Signed-in devices"
          locked={isGuest}
          hint={
            isGuest
              ? "This browser is the only place you exist."
              : "Every browser still holding a session, and a way to end any of them."
          }
        >
          {isGuest ? (
            <NeedsAccount />
          ) : (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => setSessionsOpen(true)}
            >
              <DevicesIcon size={15} />
              Manage
            </button>
          )}
        </Row>
      </Group>

      <Group title="Your data">
        <Row
          label="Download everything"
          hint={
            isGuest
              ? "Works for a guest too: the games you have played are yours."
              : "Every game, list and setting Sketchy holds about you, as one JSON file."
          }
        >
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => setDataOpen(true)}
          >
            <DownloadIcon size={15} />
            Request export
          </button>
        </Row>
        <Row
          label={isGuest ? "Delete this guest" : "Delete your account"}
          tone="danger"
          hint={
            isGuest
              ? "Removes the name, the points and the history kept against this browser."
              : "Games you played stay in other players’ histories, without your name on them."
          }
        >
          <button
            type="button"
            className="btn btn-danger-ghost btn-compact"
            onClick={() => setDeleteOpen(true)}
          >
            Delete…
          </button>
        </Row>
      </Group>

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={isGuest ? (user?.displayName ?? "") : ""}
          onClose={() => setAuthMode(null)}
          onSwitchMode={setAuthMode}
          onSubmit={authMode === "login" ? login : register}
        />
      )}
      {emailOpen && (
        <AddEmailDialog onClose={() => setEmailOpen(false)} onSaved={() => setEmailOpen(false)} />
      )}
      {sessionsOpen && <SessionManagerDialog onClose={() => setSessionsOpen(false)} />}
      {dataOpen && <AccountDataDialog onClose={() => setDataOpen(false)} />}
      {doodlesOpen && (
        <AvatarDoodleDialog
          name={user?.displayName ?? ""}
          nameColor={nameColor}
          currentUrl={user?.avatarUrl}
          onChoose={wearDoodle}
          onClose={() => setDoodlesOpen(false)}
        />
      )}
      {pendingFile && (
        <PictureCropDialog
          file={pendingFile}
          onUse={usePicture}
          onCancel={() => setPendingFile(null)}
        />
      )}
      {passwordOpen && (
        <ChangePasswordDialog
          username={user?.username ?? ""}
          canEmailLink={Boolean(email?.verified)}
          onClose={() => setPasswordOpen(false)}
        />
      )}
      {deleteOpen && (
        <DeleteAccountDialog isGuest={isGuest} onClose={() => setDeleteOpen(false)} />
      )}
    </>
  );
}

/* ------------------------------------------------------------- appearance */

function AppearancePane() {
  const theme = useSettingsStore((state) => state.theme);
  const setTheme = useSettingsStore((state) => state.setTheme);
  const colorblindSafeColors = useSettingsStore((state) => state.colorblindSafeColors);
  const setColorblindSafeColors = useSettingsStore((state) => state.setColorblindSafeColors);
  const brushCursor = useSettingsStore((state) => state.brushCursor);
  const setBrushCursor = useSettingsStore((state) => state.setBrushCursor);
  const timeFormat = useSettingsStore((state) => state.timeFormat);
  const setTimeFormat = useSettingsStore((state) => state.setTimeFormat);
  const activePlayerId = useGameStore((state) => state.playerId);

  function chooseTimeFormat(next: TimeFormat) {
    setTimeFormat(next);
    queueSettingsSync({ timeFormat: next });
  }

  function chooseTheme(next: AppTheme) {
    setTheme(next);
    queueSettingsSync({ theme: next });
  }

  function chooseColorblindSafe(next: boolean) {
    setColorblindSafeColors(next);
    queueSettingsSync({ colorblindSafeColors: next });
    // The preference stays private: the server keeps it on the live seat only
    // long enough to compute an unattributed signal for the host (R-CB-01).
    if (activePlayerId) {
      socket.emit("update_player_settings", { colorblindSafeColors: next });
    }
  }

  function chooseCursor(next: BrushCursorStyle) {
    setBrushCursor(next);
    queueSettingsSync({ brushCursor: next });
  }

  return (
    <>
      <Group title="Display">
        <Row label="Color scheme" stacked hint="Applies the moment you pick it.">
          <div className="theme-cards" role="group" aria-label="Theme">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`theme-card${theme === option.value ? " is-selected" : ""}`}
                aria-pressed={theme === option.value}
                onClick={() => chooseTheme(option.value)}
              >
                <span
                  className={`theme-card-preview theme-card-preview-${option.value}`}
                  aria-hidden="true"
                >
                  <i />
                  <i />
                </span>
                <strong>
                  {option.label}
                  {option.value === "system" && (
                    <small>Now: {getSystemTheme() === "dark" ? "dark" : "light"}</small>
                  )}
                </strong>
              </button>
            ))}
          </div>
        </Row>
        <Row
          label="Time format"
          hint="How every clock reads: chat timestamps, sign-in dates, notices. System follows your device."
        >
          <SegmentedControl
            label="Time format"
            value={timeFormat}
            options={TIME_FORMAT_OPTIONS}
            onChange={chooseTimeFormat}
          />
        </Row>
      </Group>
      {/* A fact about the player rather than a taste, so it is not a theme
          option: its own group, worded as what it says about you. */}
      <Group title="Accessibility">
        <ToggleRow
          label="I have trouble telling colors apart"
          hint="Nudges hosts toward room colors that stay distinguishable with deuteranopia and protanopia, without telling them who asked. Nothing changes on its own."
          checked={colorblindSafeColors}
          onChange={chooseColorblindSafe}
        />
      </Group>
      <Group title="The canvas">
        <Row
          label="Brush cursor"
          hint="A crosshair is precise at the point; an outline shows how wide the stroke will be."
        >
          <SegmentedControl
            label="Brush cursor style"
            value={brushCursor}
            options={BRUSH_CURSOR_OPTIONS}
            onChange={chooseCursor}
          />
        </Row>
      </Group>
    </>
  );
}

/* ------------------------------------------------------------------ sound */

function SoundPane() {
  const soundEffects = useSettingsStore((state) => state.soundEffects);
  const setSoundEffects = useSettingsStore((state) => state.setSoundEffects);
  const volume = useSettingsStore((state) => state.volume);
  const setVolume = useSettingsStore((state) => state.setVolume);
  const confettiEffects = useSettingsStore((state) => state.confettiEffects);
  const setConfettiEffects = useSettingsStore((state) => state.setConfettiEffects);

  return (
    <>
      <Group title="Sound">
        <ToggleRow
          label="Sound effects"
          hint="Chimes for a correct guess, the start of a round, the last ten seconds, and players coming and going."
          checked={soundEffects}
          onChange={(next) => {
            setSoundEffects(next);
            queueSettingsSync({ soundEffects: next });
          }}
        />
        {soundEffects && (
          <Row label="Volume">
            <span
              className="settings-volume-control"
              style={{ ["--volume-progress" as string]: `${volume * 100}%` }}
            >
              <input
                id="volume-slider"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={volume}
                onChange={(event) => {
                  const next = parseFloat(event.target.value);
                  setVolume(next);
                  // Merged with its neighbours: a drag is one request.
                  queueSettingsSync({ volume: next });
                }}
                aria-label="Volume"
              />
              <span className="settings-volume-value">{Math.round(volume * 100)}%</span>
            </span>
          </Row>
        )}
      </Group>
      <Group title="Effects">
        <ToggleRow
          label="Confetti"
          hint="A burst when you guess right, and again for the winner at the end of a game."
          checked={confettiEffects}
          onChange={(next) => {
            setConfettiEffects(next);
            queueSettingsSync({ confettiEffects: next });
          }}
        />
      </Group>
    </>
  );
}

/* -------------------------------------------------------------- shortcuts */

function ShortcutsPane() {
  const keyBindings = useSettingsStore((state) => state.keyBindings);
  const setKeyBinding = useSettingsStore((state) => state.setKeyBinding);
  const resetKeyBindings = useSettingsStore((state) => state.resetKeyBindings);
  const [rebinding, setRebinding] = useState<{
    action: keyof KeyBindings;
    slotIndex: number;
  } | null>(null);
  // Keyed on the pointer rather than the width: a tablet with a keyboard is a
  // narrow screen that can still use these. The section stays in the rail on
  // touch and explains itself, rather than vanishing.
  const hasKeyboard = useMediaQuery("(pointer: fine)");
  const actions = Object.keys(ACTION_LABELS) as (keyof KeyBindings)[];

  useEffect(() => {
    if (!rebinding) return;
    const { action, slotIndex } = rebinding;
    function onKeyDown(event: KeyboardEvent) {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Escape") {
        setRebinding(null);
        return;
      }
      if (["Control", "Shift", "Alt", "Meta"].includes(event.key)) return;
      const keys = [...(keyBindings[action] || [])];
      keys[slotIndex] = event.key.toLowerCase();
      const unique = Array.from(new Set(keys.filter(Boolean)));
      setKeyBinding(action, unique);
      queueSettingsSync({ keyBindings: { ...keyBindings, [action]: unique } });
      setRebinding(null);
    }
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [rebinding, keyBindings, setKeyBinding]);

  return (
    <>
      {!hasKeyboard && (
        <div className="settings-empty">
          <KeyboardIcon size={28} />
          <b>No keyboard on this device</b>
          <span>
            Your bindings are still saved and still work. Open Sketchy with a keyboard
            attached to change them.
          </span>
        </div>
      )}
      <Group
        title="Drawing tools"
        hint="Click a key to rebind it. Each action can hold two. Press Esc to cancel."
        action={
          <button
            type="button"
            className="btn btn-ghost btn-compact"
            onClick={() => {
              resetKeyBindings();
              setRebinding(null);
              queueSettingsSync({ keyBindings: DEFAULT_KEY_BINDINGS });
            }}
          >
            Reset to defaults
          </button>
        }
      >
        <div className="keybindings-grid">
          {actions.map((action) => {
            const keys = keyBindings[action] || [];
            const defaults = DEFAULT_KEY_BINDINGS[action] || [];
            const slotButton = (slotIndex: number, secondary: boolean) => {
              const active = rebinding?.action === action && rebinding.slotIndex === slotIndex;
              const key = keys[slotIndex];
              return (
                <button
                  type="button"
                  className={`kbd-badge${secondary ? " secondary" : ""}${active ? " rebinding" : ""}`}
                  onClick={() => setRebinding({ action, slotIndex })}
                  title={secondary ? "Click to rebind the second key" : "Click to rebind"}
                >
                  {active ? "Press key…" : key ? formatKey(key) : secondary ? "+ key" : "None"}
                </button>
              );
            };
            return (
              <div key={action} className="keybinding-row">
                <span className="keybinding-icon" aria-hidden="true">
                  {ACTION_ICONS[action]}
                </span>
                <span className="keybinding-label">{ACTION_LABELS[action]}</span>
                <div className="keybinding-badges">
                  {slotButton(0, false)}
                  {(defaults.length > 1 || keys.length > 1) && slotButton(1, true)}
                </div>
              </div>
            );
          })}
        </div>
      </Group>
    </>
  );
}

/* ---------------------------------------------------------------- the pane */

/**
 * Settings, over the page it was opened from (R-SET-06).
 *
 * Four sections in one rail on every device, and rows that apply as they
 * change (R-SET-05): there is no Save and no Discard, because nothing here is
 * a transaction. A write the account refuses is reported as a toast; success
 * is silent. The rows the server can refuse - the display name, the email
 * address, the password - keep a button of their own.
 */
export function SettingsOverlay() {
  const navigate = useNavigate();
  const location = useLocation();
  const section = sectionFromPath(location.pathname);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const { notify } = useToast();

  const isGuest = useAuthStore((state) => Boolean(state.user?.isAnonymous));

  // R-SET-03: logging in makes the account's copy authoritative, so a guest
  // who signs in from here watches their theme change. Said once, rather than
  // left to look like a glitch.
  const arrivedAsGuest = useRef(isGuest);
  const [signedInHere, setSignedInHere] = useState(false);
  useEffect(() => {
    if (arrivedAsGuest.current && !isGuest) setSignedInHere(true);
  }, [isGuest]);

  useEffect(() => {
    onSettingsSyncError((message) => notify(message, "error"));
    return () => {
      onSettingsSyncError(null);
      // Whatever is still waiting for company goes out as the pane closes.
      void flushSettingsSync();
    };
  }, [notify]);

  function close() {
    void flushSettingsSync();
    // Back to the page it was opened over, so a room stays the room. Somebody
    // who typed the URL has nothing to go back to and gets the lobby, which is
    // what was drawn underneath them anyway.
    const state = location.state as SettingsLocationState | null;
    if (state?.settingsBackground) navigate(-1);
    else navigate("/", { replace: true });
  }

  function showSection(next: SettingsSection) {
    // Replace rather than push: the rail is one screen, and Back should leave
    // Settings rather than walk through the sections visited.
    navigate(settingsPath(next), { replace: true, state: location.state });
  }

  useFocusTrap(dialogRef, { onEscape: close, initialFocusRef: closeButtonRef });

  return (
    <div
      className="modal-overlay settings-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card settings-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="settings"
      >
        <div className="settings-modal-header">
          <h3 id={titleId}>
            <GearIcon size={20} />
            <span>Settings</span>
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            className="close-icon-button"
            onClick={close}
            title="Close"
            aria-label="Close settings"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="settings-modal-body">
          <div className="settings-tabs" role="tablist" aria-label="Settings sections">
            {SETTINGS_SECTIONS.map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`settings-tab-${id}`}
                aria-selected={section === id}
                aria-controls={`settings-panel-${id}`}
                className={`settings-tab-button${section === id ? " active" : ""}`}
                onClick={() => showSection(id)}
              >
                <span className="settings-tab-icon" aria-hidden="true">
                  {SECTION_ICONS[id]}
                </span>
                <span className="settings-tab-text">{SECTION_LABELS[id]}</span>
              </button>
            ))}
          </div>

          <div
            className="settings-tab-content"
            role="tabpanel"
            id={`settings-panel-${section}`}
            aria-labelledby={`settings-tab-${section}`}
          >
            {section === "account" && <AccountPane signedInHere={signedInHere} />}
            {section === "appearance" && <AppearancePane />}
            {section === "sound" && <SoundPane />}
            {section === "shortcuts" && <ShortcutsPane />}
          </div>
        </div>
      </div>
    </div>
  );
}
