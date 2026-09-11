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
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { flushSettingsSync, queueSettingsSync } from "../lib/accountSettingsSync";
import { maskEmail, readEmailState, type EmailState } from "../lib/accountRecovery";
import { removeAvatar, uploadAvatar } from "../lib/avatars";
import { TwoFactorDialog } from "./TwoFactorDialog";
import { roleName } from "../lib/operatorAccess";
import { fetchSecondFactor, type SecondFactorState } from "../lib/secondFactor";
import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  SETTINGS_SECTIONS,
  sectionFromPath,
  settingsPath,
  type SettingsSection,
} from "../hooks/useSettingsRoute";
import { useCloseOverlay } from "../hooks/useOverlayRoute";
import { AuthDialog } from "./AccountMenu";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { AddEmailDialog } from "./AddEmailDialog";
import { SessionManagerDialog } from "./SessionManagerDialog";
import { AccountDataDialog } from "./AccountDataDialog";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { PictureCropDialog } from "./PictureCropDialog";
import { DeleteAccountDialog } from "./DeleteAccountDialog";
import { SegmentedControl } from "./RoomSetupControls";
import { SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import { LanguagePicker } from "./LanguagePicker";
import type { PromptLanguage } from "../types";
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
  ShieldIcon,
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
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { LOCALES, type Locale } from "../lib/interfaceLocale.ts";
import { useInterfaceLocale } from "../hooks/useInterfaceLocale";

/* ------------------------------------------------------------- vocabulary */

const SECTION_LABELS: Record<SettingsSection, string> = {
  get account() { return ui.settingsOverlay.account; },
  get appearance() { return ui.settingsOverlay.appearance; },
  get sound() { return ui.settingsOverlay.soundEffects2; },
  get shortcuts() { return ui.settingsOverlay.shortcuts; },
};

const SECTION_ICONS: Record<SettingsSection, ReactNode> = {
  account: <UserIcon size={16} />,
  appearance: <SunIcon size={16} />,
  sound: <VolumeIcon size={16} />,
  shortcuts: <KeyboardIcon size={16} />,
};

/** The palette, with a name a screen reader can say instead of a hex. */
const NAME_COLOR_NAMES: Record<(typeof NAME_COLOR_PALETTE)[number], string> = {
  get "#e11d48"() { return ui.settingsOverlay.red; },
  get "#f97316"() { return ui.settingsOverlay.orange; },
  get "#eab308"() { return ui.settingsOverlay.yellow; },
  get "#84cc16"() { return ui.settingsOverlay.lime; },
  get "#16a34a"() { return ui.settingsOverlay.green; },
  get "#0d9488"() { return ui.settingsOverlay.teal; },
  get "#38bdf8"() { return ui.settingsOverlay.sky; },
  get "#2563eb"() { return ui.settingsOverlay.blue; },
  get "#6366f1"() { return ui.settingsOverlay.indigo; },
  get "#a855f7"() { return ui.settingsOverlay.purple; },
  get "#d946ef"() { return ui.settingsOverlay.magenta; },
  get "#f472b6"() { return ui.settingsOverlay.pink; },
  get "#a0522d"() { return ui.settingsOverlay.brown; },
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
  { value: "light", get label() { return ui.settingsOverlay.light; } },
  { value: "dark", get label() { return ui.settingsOverlay.dark; } },
  { value: "system", get label() { return ui.settingsOverlay.system; } },
];

const TIME_FORMAT_OPTIONS: { value: TimeFormat; label: string }[] = [
  { value: "system", get label() { return ui.settingsOverlay.system; } },
  { value: "12h", label: "12-hour" },
  { value: "24h", label: "24-hour" },
];

const BRUSH_CURSOR_OPTIONS: { value: BrushCursorStyle; label: string }[] = [
  { value: "crosshair", get label() { return ui.settingsOverlay.crosshair; } },
  { value: "circle", get label() { return ui.settingsOverlay.outline; } },
];

function formatKey(key: string): string {
  if (key === " ") return ui.settingsOverlay.space;
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
      {ui.settingsOverlay.needsAccount}
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
        aria-label={revealed ? ui.settingsOverlay.hideTheFullAddress : ui.settingsOverlay.showTheFullAddress}
        title={revealed ? ui.settingsOverlay.hide : ui.settingsOverlay.showInFull}
        onClick={() => setRevealed((shown) => !shown)}
      >
        {revealed ? <EyeOffIcon size={14} /> : <EyeIcon size={14} />}
      </button>
      <span className={`settings-email-status ${verified ? "is-verified" : "is-unverified"}`}>
        {verified ? <CheckIcon size={12} /> : <ClockIcon size={12} />}
        {verified ? ui.settingsOverlay.verified : ui.settingsOverlay.notVerified}
      </span>
    </span>
  );
}

/**
 * The pencil on the disc's corner. With no picture it opens the file picker;
 * with one it opens a two-item menu, because "Remove" needs a home once the
 * picture row is gone. The menu is a real menu: Escape, outside click and
 * the arrow keys all work, the way the account menu's do.
 */
function PictureEditChip({
  hasPicture,
  busy,
  onChoose,
  onRemove,
}: {
  hasPicture: boolean;
  busy: boolean;
  onChoose: (file: File | undefined) => void;
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
        aria-label={ui.settingsOverlay.choosePicture}
        onChange={(event) => {
          onChoose(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        className="settings-you-edit-chip"
        disabled={busy}
        aria-label={ui.settingsOverlay.editPicture}
        title={ui.settingsOverlay.editPicture}
        aria-haspopup={hasPicture ? "menu" : undefined}
        aria-expanded={hasPicture ? open : undefined}
        aria-controls={hasPicture && open ? menuId : undefined}
        onClick={() => (hasPicture ? setOpen((shown) => !shown) : pick())}
      >
        <PencilIcon size={14} />
      </button>
      {hasPicture && open && (
        <div
          ref={menuRef}
          id={menuId}
          className="settings-you-menu"
          role="menu"
          aria-label={ui.settingsOverlay.picture}
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          <button type="button" role="menuitem" onClick={pick}>
            <ImageIcon size={15} />
            {ui.settingsOverlay.changePicture}
          </button>
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
            {ui.settingsOverlay.removePicture}
          </button>
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
  const pendingRole = user?.pendingRole ?? null;
  // Staff have one to manage; somebody who has been offered a role has one to
  // set up. Everybody else is shown nothing about it at all.
  const showsTwoFactor =
    !isGuest && (user?.role === "moderator" || user?.role === "admin" || Boolean(pendingRole));
  const activePlayerId = useGameStore((state) => state.playerId);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const setLocalNameColor = useSettingsStore((state) => state.setNameColor);

  const [draftName, setDraftName] = useState(user?.displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [pictureBusy, setPictureBusy] = useState(false);
  const [pictureError, setPictureError] = useState<string | null>(null);
  // A chosen file opens the crop dialog; the dialog uploads what was framed.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [editingName, setEditingName] = useState(false);

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
        refusalText(error, ui.settingsOverlay.couldNotRemovePicture),
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
  const [twoFactorOpen, setTwoFactorOpen] = useState(false);
  // Only so the row can say "Set up" or "Manage"; the dialog reads its own
  // state when it opens. Read when the pane appears rather than only after
  // the dialog has been opened once, or an account that already has a second
  // factor is invited to "Set up" another.
  const [twoFactorState, setTwoFactorState] = useState<SecondFactorState | null>(null);
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

  // The same shape as the email row above, and re-read when the dialog
  // closes so the label follows what just happened in it.
  useEffect(() => {
    if (!showsTwoFactor) return;
    let active = true;
    void fetchSecondFactor()
      .then((state) => {
        if (active) setTwoFactorState(state);
      })
      .catch(() => {
        // The row falls back to offering the dialog, which reads its own
        // state when it opens.
      });
    return () => {
      active = false;
    };
  }, [showsTwoFactor, twoFactorOpen]);

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
          setNameError(refusalText(response, ui.settingsOverlay.couldNotChangeYourDisplayName));
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
        refusalText(error, ui.settingsOverlay.couldNotChangeYourDisplayName2),
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
            <b>{ui.settingsOverlay.theseAreTheirSettings({ name: user?.username ?? "" })}</b> {ui.settingsOverlay.themeSoundShortcutsCameFromAccount}
          </p>
          <button type="button" aria-label={ui.settingsOverlay.dismiss} onClick={() => setNoticeOpen(false)}>
            <XIcon size={14} />
          </button>
        </div>
      )}

      {isGuest && (
        <div className="settings-guest-card">
          <b>{ui.settingsOverlay.playingAsGuest}</b>
          <p>
            {ui.settingsOverlay.guestLivesInThisBrowser({
              name: user?.displayName ?? "",
            })}
          </p>
          <div className="settings-guest-actions">
            <button type="button" className="btn btn-primary" onClick={() => setAuthMode("claim")}>
              <PlusIcon size={15} />
              {ui.settingsOverlay.createAccount}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setAuthMode("login")}>
              <KeyIcon size={15} />
              {ui.settingsOverlay.logIn}
            </button>
          </div>
        </div>
      )}

      <Group title={ui.settingsOverlay.you}>
        {/* The identity card: disc, name in its colour, palette. A registered
            player always plays as their username (R-ACCT-05), so only a guest
            gets a way to change the name; and only an account gets a picture
            or a colour, because the grey initial is what marks a guest. */}
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
                    aria-label={ui.settingsOverlay.displayName}
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
                    {nameBusy ? ui.settingsOverlay.saving : ui.settingsOverlay.save}
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
                    {ui.settingsOverlay.cancel}
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
                      {ui.settingsOverlay.change}
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
              <span className="settings-swatches" role="group" aria-label={ui.settingsOverlay.nameColor}>
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

      <Group title={ui.settingsOverlay.signingIn}>
        <Row
          label={ui.settingsOverlay.email}
          locked={isGuest}
          hint={
            isGuest ? (
              ui.settingsOverlay.aGuestHasNothingTo
            ) : shownAddress ? (
              <EmailAddressStatus address={shownAddress} verified={shownVerified} />
            ) : (
              ui.settingsOverlay.withoutOneThereIsNo
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
              {shownAddress ? ui.settingsOverlay.change : ui.settingsOverlay.addAnEmail}
            </button>
          )}
        </Row>
        <Row
          label={ui.settingsOverlay.password}
          locked={isGuest}
          hint={
            isGuest ? ui.settingsOverlay.guestsHaveNoPassword : ui.settingsOverlay.changingItSignsEveryOther
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
              {ui.settingsOverlay.changePassword}
            </button>
          )}
        </Row>
        {/* Only for the accounts it means anything to (R-AUTH-20). A second
            factor is not something an ordinary player can use here - it does
            not gate their sign-in, and there is no way back from a lost
            authenticator the way there is from a lost password - so it is a
            staff control, and it appears when somebody is staff or has just
            been offered a role that waits on it. */}
        {showsTwoFactor && (
          <Row
            label={ui.settingsOverlay.twoFactorAuthentication}
            hint={
              pendingRole
                ? ui.settingsOverlay.setThisUpAndThe({ pendingRole: roleName(pendingRole) })
                : ui.settingsOverlay.anAuthenticatorAppSCode
            }
          >
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => setTwoFactorOpen(true)}
            >
              <ShieldIcon size={15} />
              {twoFactorState && (twoFactorState.enrolled || twoFactorState.passkeys > 0)
                ? ui.settingsOverlay.manage
                : ui.settingsOverlay.setUp}
            </button>
          </Row>
        )}
        <Row
          label={ui.settingsOverlay.signedDevices}
          locked={isGuest}
          hint={
            isGuest
              ? ui.settingsOverlay.thisBrowserIsTheOnly
              : ui.settingsOverlay.everyBrowserStillHoldingA
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
              {ui.settingsOverlay.manage}
            </button>
          )}
        </Row>
      </Group>

      <Group title={ui.settingsOverlay.yourData}>
        <Row
          label={ui.settingsOverlay.downloadEverything}
          hint={
            isGuest
              ? ui.settingsOverlay.worksForAGuestToo
              : ui.settingsOverlay.everyGameListAndSetting
          }
        >
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => setDataOpen(true)}
          >
            <DownloadIcon size={15} />
            {ui.settingsOverlay.requestExport}
          </button>
        </Row>
        <Row
          label={isGuest ? ui.settingsOverlay.deleteThisGuest : ui.settingsOverlay.deleteYourAccount}
          tone="danger"
          hint={
            isGuest
              ? ui.settingsOverlay.removesTheNameThePoints
              : ui.settingsOverlay.gamesYouPlayedStayIn
          }
        >
          <button
            type="button"
            className="btn btn-danger-ghost btn-compact"
            onClick={() => setDeleteOpen(true)}
          >
            {ui.settingsOverlay.delete}
          </button>
        </Row>
      </Group>

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={isGuest ? (user?.displayName ?? "") : ""}
          onClose={() => setAuthMode(null)}
          onSwitchMode={setAuthMode}
          onSubmit={authSubmitter(authMode, login, register)}
        />
      )}
      {emailOpen && (
        <AddEmailDialog onClose={() => setEmailOpen(false)} onSaved={() => setEmailOpen(false)} />
      )}
      {sessionsOpen && <SessionManagerDialog onClose={() => setSessionsOpen(false)} />}
      {twoFactorOpen && (
        <TwoFactorDialog onClose={() => setTwoFactorOpen(false)} />
      )}
      {dataOpen && <AccountDataDialog onClose={() => setDataOpen(false)} />}
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
  const promptLanguage = useSettingsStore((state) => state.promptLanguage);
  const setPromptLanguage = useSettingsStore((state) => state.setPromptLanguage);
  const [locale, chooseLocale] = useInterfaceLocale();
  const activePlayerId = useGameStore((state) => state.playerId);

  function choosePromptLanguage(next: PromptLanguage) {
    setPromptLanguage(next);
    queueSettingsSync({ promptLanguage: next });
  }

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
      <Group title={ui.settingsOverlay.display}>
        <Row label={ui.settingsOverlay.colorScheme} stacked hint={ui.settingsOverlay.appliesMomentYouPick}>
          <div className="theme-cards" role="group" aria-label={ui.settingsOverlay.theme}>
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
                    <small>{ui.settingsOverlay.systemThemeNow({ theme: getSystemTheme() === "dark" ? "dark" : "light" })}</small>
                  )}
                </strong>
              </button>
            ))}
          </div>
        </Row>
        {/* Two languages, next to each other because that is the only place
            the difference is obvious: what you read, and what you play in.
            Reading in Dutch while playing an English room is ordinary
            (R-I18N-06). */}
        <Row
          label={ui.settingsOverlay.interfaceLanguage}
          hint={ui.settingsOverlay.interfaceLanguageHint}
        >
          <LanguagePicker
            label={ui.settingsOverlay.interfaceLanguage}
            value={locale}
            options={LOCALES}
            onChange={(next) => chooseLocale(next as Locale)}
          />
        </Row>
        <Row
          label={ui.settingsOverlay.languageYouPlay}
          hint={ui.settingsOverlay.roomsThisLanguageComeFirstLobby}
        >
          <LanguagePicker
            label={ui.settingsOverlay.languageYouPlay}
            value={promptLanguage}
            options={SUPPORTED_PROMPT_LANGUAGES}
            onChange={(next) => choosePromptLanguage(next as PromptLanguage)}
          />
        </Row>
        <Row
          label={ui.settingsOverlay.timeFormat}
          hint={ui.settingsOverlay.howEveryClockReadsChatTimestamps}
        >
          <SegmentedControl
            label={ui.settingsOverlay.timeFormat}
            value={timeFormat}
            options={TIME_FORMAT_OPTIONS}
            onChange={chooseTimeFormat}
          />
        </Row>
      </Group>
      {/* A fact about the player rather than a taste, so it is not a theme
          option: its own group, worded as what it says about you. */}
      <Group title={ui.settingsOverlay.accessibility}>
        <ToggleRow
          label={ui.settingsOverlay.iHaveTroubleTellingColorsApart}
          hint={ui.settingsOverlay.nudgesHostsTowardRoomColorsThat}
          checked={colorblindSafeColors}
          onChange={chooseColorblindSafe}
        />
      </Group>
      <Group title={ui.settingsOverlay.theCanvas}>
        <Row
          label={ui.settingsOverlay.brushCursor}
          hint={ui.settingsOverlay.crosshairPreciseAtPointOutlineShows}
        >
          <SegmentedControl
            label={ui.settingsOverlay.brushCursorStyle}
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
      <Group title={ui.settingsOverlay.sound}>
        <ToggleRow
          label={ui.settingsOverlay.soundEffects}
          hint={ui.settingsOverlay.chimesCorrectGuessStartRoundLast}
          checked={soundEffects}
          onChange={(next) => {
            setSoundEffects(next);
            queueSettingsSync({ soundEffects: next });
          }}
        />
        {soundEffects && (
          <Row label={ui.settingsOverlay.volume2}>
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
                aria-label={ui.settingsOverlay.volume}
              />
              <span className="settings-volume-value">{Math.round(volume * 100)}%</span>
            </span>
          </Row>
        )}
      </Group>
      <Group title={ui.settingsOverlay.effects}>
        <ToggleRow
          label={ui.settingsOverlay.confetti}
          hint={ui.settingsOverlay.burstWhenYouGuessRightAgain}
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
          <b>{ui.settingsOverlay.noKeyboardThisDevice}</b>
          <span>
            {ui.settingsOverlay.yourBindingsAreStillSavedStill}
          </span>
        </div>
      )}
      <Group
        title={ui.settingsOverlay.drawingTools}
        hint={ui.settingsOverlay.clickKeyRebindEachActionCan}
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
            {ui.settingsOverlay.resetDefaults}
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
                  title={secondary ? ui.settingsOverlay.clickToRebindTheSecond : ui.settingsOverlay.clickToRebind}
                >
                  {active ? ui.settingsOverlay.pressKey : key ? formatKey(key) : secondary ? ui.settingsOverlay.key : ui.settingsOverlay.none}
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
  const closeOverlay = useCloseOverlay();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  const isGuest = useAuthStore((state) => Boolean(state.user?.isAnonymous));

  // R-SET-03: logging in makes the account's copy authoritative, so a guest
  // who signs in from here watches their theme change. Said once, rather than
  // left to look like a glitch.
  const arrivedAsGuest = useRef(isGuest);
  const [signedInHere, setSignedInHere] = useState(false);
  useEffect(() => {
    if (arrivedAsGuest.current && !isGuest) setSignedInHere(true);
  }, [isGuest]);

  // A refused save is reported app-wide (SettingsSyncNotices), since the
  // lobby saves settings too; what is still waiting for company goes out as
  // the pane closes.
  useEffect(() => () => void flushSettingsSync(), []);

  function close() {
    void flushSettingsSync();
    // Back to the page it was opened over, so a room stays the room. Shared
    // with Friends, which needs the same thing for the same reason.
    closeOverlay();
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
            <span>{ui.settingsOverlay.settings}</span>
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            className="close-icon-button"
            onClick={close}
            title={ui.settingsOverlay.close}
            aria-label={ui.settingsOverlay.closeSettings}
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="settings-modal-body">
          <div className="settings-tabs" role="tablist" aria-label={ui.settingsOverlay.settingsSections}>
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
