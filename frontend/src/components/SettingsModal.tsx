import { useEffect, useId, useRef, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { emitWithAck } from "../lib/socket";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { ApiError } from "../lib/api";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { FieldHint, SegmentedControl, Switch } from "./RoomSetupControls";
import {
  BrushIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  CircleIcon,
  EraserIcon,
  FillIcon,
  GearIcon,
  KeyboardIcon,
  RectIcon,
  TriangleIcon,
  UndoIcon,
  XIcon,
} from "./icons";
import { getSystemTheme } from "../store/settingsStore";
import type { ReactNode } from "react";
import {
  ACTION_LABELS,
  DEFAULT_KEY_BINDINGS,
  randomNameColor,
  type AppTheme,
  type KeyBindings,
  type BrushCursorStyle,
  useSettingsStore,
} from "../store/settingsStore";
import { socket } from "../lib/socket";
import { patchUserSettings } from "../lib/userSettings";
import { useMediaQuery } from "../hooks/useMediaQuery";

type SettingsTab = "general" | "game" | "shortcuts";

const TABS: { id: SettingsTab; label: string; sub: string; icon: ReactNode }[] = [
  { id: "general", label: "General", sub: "Account, appearance & sound", icon: <GearIcon size={16} /> },
  { id: "game", label: "Game", sub: "Drawing & celebrations", icon: <BrushIcon size={16} /> },
  { id: "shortcuts", label: "Shortcuts", sub: "Drawing tool key bindings", icon: <KeyboardIcon size={16} /> },
];

const ACTION_ICONS: Record<string, ReactNode> = {
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

const BRUSH_CURSOR_OPTIONS: { value: BrushCursorStyle; label: string }[] = [
  { value: "crosshair", label: "Crosshair" },
  { value: "circle", label: "Outline" },
];

function formatKey(key: string): string {
  if (key === " ") return "Space";
  if (key.length === 1) return key.toUpperCase();
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function SettingsModalContent() {
  const { closeSettings, keyBindings, brushCursor, theme, confettiEffects, soundEffects, volume, colorblindSafeColors, autoClearChatOnGuess, customBrushPresets, nameColor, setAllSettings } =
    useSettingsStore();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  // Nothing on a touch device can use a key binding, so the tab is not offered
  // there. Keyed on the pointer rather than the width: a tablet with a
  // keyboard is a narrow screen that can still use them.
  const hasKeyboard = useMediaQuery("(pointer: fine)");
  const tabs = hasKeyboard ? TABS : TABS.filter((tab) => tab.id !== "shortcuts");
  const [draftKeyBindings, setDraftKeyBindings] = useState<KeyBindings>(keyBindings);
  const [draftBrushCursor, setDraftBrushCursor] = useState<BrushCursorStyle>(brushCursor);
  const [draftTheme, setDraftTheme] = useState<AppTheme>(theme);
  const [draftConfettiEffects, setDraftConfettiEffects] = useState<boolean>(confettiEffects);
  const [draftSoundEffects, setDraftSoundEffects] = useState<boolean>(soundEffects);
  const [draftVolume, setDraftVolume] = useState<number>(volume);
  const [draftColorblindSafeColors, setDraftColorblindSafeColors] =
    useState<boolean>(colorblindSafeColors);
  // The clear-guess-box behavior kept its wire key but lost its settings row;
  // the stored value passes through untouched.
  const [draftAutoClearChatOnGuess] = useState<boolean>(autoClearChatOnGuess);
  const [draftNameColor, setDraftNameColor] = useState<string>(nameColor);
  const authUser = useAuthStore((state) => state.user);
  const setDisplayName = useAuthStore((state) => state.setDisplayName);
  const setNameColor = useAuthStore((state) => state.setNameColor);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const logout = useAuthStore((state) => state.logout);
  const activePlayerId = useGameStore((state) => state.playerId);
  const isGuest = Boolean(authUser?.isAnonymous);
  const [draftName, setDraftName] = useState<string>(authUser?.displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [activeRebind, setActiveRebind] = useState<{
    action: keyof KeyBindings;
    slotIndex: number;
  } | null>(null);

  useEffect(() => {
    if (!activeRebind) return;

    function handleKeyDown(e: KeyboardEvent) {
      e.preventDefault();
      e.stopPropagation();

      if (e.key === "Escape") {
        setActiveRebind(null);
        return;
      }

      // Ignore lone modifier keypresses like Shift or Control
      if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) {
        return;
      }

      if (!activeRebind) return;
      const keyChar = e.key.toLowerCase();
      const { action, slotIndex } = activeRebind;
      const currentKeys = [...(draftKeyBindings[action] || [])];

      currentKeys[slotIndex] = keyChar;
      // Deduplicate keys for the same action
      const uniqueKeys = Array.from(new Set(currentKeys.filter(Boolean)));

      setDraftKeyBindings((prev) => ({
        ...prev,
        [action]: uniqueKeys,
      }));
      setActiveRebind(null);
    }

    window.addEventListener("keydown", handleKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", handleKeyDown, { capture: true });
  }, [activeRebind, draftKeyBindings]);

  const handleDiscard = () => {
    closeSettings();
  };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    const trimmedName = draftName.trim();
    const nameChanged = isGuest && trimmedName !== (authUser?.displayName ?? "");
    if (nameChanged) {
      const invalid = nicknameError(trimmedName);
      if (invalid) {
        setNameError(invalid);
        setActiveTab("general");
        setSaving(false);
        return;
      }
      try {
        // In a room the socket owns the change so the seat and the other
        // players update; outside one, writing the account is enough.
        if (activePlayerId) {
          const response = await emitWithAck<{ ok: boolean; error?: string }>(
            "rename_player",
            { nickname: trimmedName },
          );
          if (!response.ok) {
            setNameError(response.error || "Could not change your display name.");
            setActiveTab("general");
            setSaving(false);
            return;
          }
          await useAuthStore.getState().fetchMe();
        } else {
          await setDisplayName(trimmedName);
        }
      } catch (error) {
        // Surface the server's reason - "that name belongs to a registered
        // player" is the whole point of the check, and a generic message would
        // leave the player guessing why it was refused.
        setNameError(
          error instanceof ApiError
            ? error.message
            : "Could not change your display name. Please try again.",
        );
        setActiveTab("general");
        setSaving(false);
        return;
      }
    }

    const persistedSettings = {
      keyBindings: draftKeyBindings,
      brushCursor: draftBrushCursor,
      theme: draftTheme,
      confettiEffects: draftConfettiEffects,
      soundEffects: draftSoundEffects,
      volume: draftVolume,
      colorblindSafeColors: draftColorblindSafeColors,
      autoClearChatOnGuess: draftAutoClearChatOnGuess,
      customBrushPresets,
    };
    if (!isGuest) {
      try {
        await patchUserSettings(persistedSettings);
      } catch (error) {
        setSaveError(
          error instanceof ApiError
            ? error.message
            : "Could not save settings to your account. Please try again.",
        );
        setSaving(false);
        return;
      }
    }

    setAllSettings({
      ...persistedSettings,
      nameColor: draftNameColor,
    });
    if (activePlayerId) {
      // The preference stays private: the server retains it on the live seat
      // only long enough to compute an unattributed signal for the host.
      socket.emit("update_player_settings", {
        colorblindSafeColors: draftColorblindSafeColors,
        ...(!isGuest ? { nameColor: draftNameColor } : {}),
      });
    }
    // Guests are pinned to the guest grey server-side, so sending a color
    // would only be rejected.
    if (!isGuest) {
      // The socket recolours the room the player is in right now; the account
      // write is what makes the choice outlast this room and show up on their
      // profile. Neither is a reason to keep the dialog open, and a failed
      // save is not worth an error over a color.
      void setNameColor(draftNameColor).catch(() => {});
    }
    setSaving(false);
    closeSettings();
  };

  const handleResetDefaults = () => {
    setDraftKeyBindings(DEFAULT_KEY_BINDINGS);
    setActiveRebind(null);
  };

  useFocusTrap(dialogRef, {
    onEscape: handleDiscard,
    initialFocusRef: closeButtonRef,
  });

  const actionKeys = Object.keys(ACTION_LABELS) as (keyof KeyBindings)[];

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleDiscard();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card settings-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className="settings-modal-header">
          <h3 id={titleId} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <GearIcon size={20} />
            <span>Settings</span>
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            className="close-icon-button"
            onClick={handleDiscard}
            title="Close"
            aria-label="Close settings"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="settings-modal-body">
        <div className="settings-tabs" role="tablist" aria-orientation="vertical">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`settings-tab-button${activeTab === tab.id ? " active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="settings-tab-icon" aria-hidden="true">{tab.icon}</span>
              <span className="settings-tab-text">
                <strong>{tab.label}</strong>
                <small>{tab.sub}</small>
              </span>
            </button>
          ))}
        </div>

        <div className="settings-tab-content">
          {activeTab === "general" && (
            <div className="settings-section">
              <div className="settings-fields">
                <h4 className="settings-fields-heading">You</h4>

                <div className="settings-labeled-field">
                  <label
                    className="settings-labeled-field-label"
                    htmlFor="settings-display-name"
                  >
                    {isGuest ? "Display name" : "Username"}
                    <FieldHint hint={isGuest ? "Used as your default nickname." : "Your account login and nickname."} />
                  </label>
                  <input
                    id="settings-display-name"
                    type="search"
                    inputMode="text"
                    value={isGuest ? draftName : (authUser?.username ?? "")}
                    onChange={(event) => {
                      setDraftName(event.target.value);
                      setNameError(null);
                    }}
                    maxLength={MAX_NICKNAME_LENGTH}
                    autoComplete="nickname"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    /* A registered player is their username; changing it here
                       would let the two drift apart. */
                    disabled={!isGuest}
                    aria-describedby={nameError ? "settings-name-error" : undefined}
                  />
                  {nameError && (
                    <p id="settings-name-error" className="auth-error" role="alert">
                      {nameError}
                    </p>
                  )}
                </div>

                <div className="settings-labeled-field settings-account-field">
                  <span className="settings-labeled-field-label">Account</span>
                  {isGuest ? (
                    <div className="settings-account-row">
                      <span className="settings-account-status">
                        Playing as a guest — your display name isn’t saved.
                      </span>
                      <button
                        type="button"
                        className="settings-account-action"
                        onClick={() => setAuthMode("claim")}
                      >
                        Create account
                      </button>
                      <button
                        type="button"
                        className="auth-link"
                        onClick={() => setAuthMode("login")}
                      >
                        Log in
                      </button>
                    </div>
                  ) : (
                    <div className="settings-account-row">
                      <span className="settings-account-status">
                        Signed in as <strong>{authUser?.username}</strong>
                      </span>
                      <button
                        type="button"
                        className="settings-account-action"
                        onClick={() => void logout()}
                      >
                        Log out
                      </button>
                    </div>
                  )}
                </div>

                <div className="settings-labeled-field name-color-setting">
                  <span className="settings-labeled-field-label">
                    Name color
                    <FieldHint hint="This color is visible to everyone in rooms you join." />
                  </span>
                  {isGuest ? (
                    /* Guests are pinned to the guest grey server-side. Showing
                       a working picker here would be a control that silently
                       does nothing. */
                    <p className="settings-locked-hint">
                      Guests play in grey. Create an account to pick a color.
                    </p>
                  ) : (
                    <div className="name-color-controls">
                      <input
                        id="name-color-input"
                        type="color"
                        value={draftNameColor}
                        onChange={(event) => setDraftNameColor(event.target.value)}
                        aria-label="Name color"
                      />
                      <strong style={{ color: draftNameColor }}>Your colored name</strong>
                      <button
                        type="button"
                        className="name-color-randomize"
                        onClick={() => setDraftNameColor(randomNameColor(draftNameColor))}
                      >
                        Randomize
                      </button>
                    </div>
                  )}
                </div>

                <h4 className="settings-fields-heading">Appearance</h4>
                <div className="settings-labeled-field">
                  <span className="settings-labeled-field-label">
                    Theme
                    <FieldHint hint="Follow your device preference, or lock Light / Dark." />
                  </span>
                  <div className="theme-cards" role="group" aria-label="Theme">
                    {THEME_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`theme-card${draftTheme === option.value ? " is-selected" : ""}`}
                        aria-pressed={draftTheme === option.value}
                        onClick={() => setDraftTheme(option.value)}
                      >
                        <span className={`theme-card-preview theme-card-preview-${option.value}`} aria-hidden="true">
                          <i />
                          <i />
                        </span>
                        <strong>
                          {option.label}
                          {option.value === "system" && (
                            <small>Current: {getSystemTheme() === "dark" ? "Dark" : "Light"}</small>
                          )}
                        </strong>
                      </button>
                    ))}
                  </div>
                </div>

                <Switch
                  label="Prefer colorblind-safe colors"
                  hint="Suggest colorblind-safe room colors to a host without exposing who requested them."
                  checked={draftColorblindSafeColors}
                  onChange={setDraftColorblindSafeColors}
                />

                <h4 className="settings-fields-heading">Audio</h4>
                <Switch
                  label="Sound effects"
                  hint="Enable Web Audio chimes for guesses, round start, timer warnings, and player events."
                  checked={draftSoundEffects}
                  onChange={setDraftSoundEffects}
                />

                {draftSoundEffects && (
                  <div className="settings-labeled-field">
                    <span className="settings-labeled-field-label">Master volume</span>
                    <div
                      className="settings-volume-control"
                      style={{ ["--volume-progress" as string]: `${draftVolume * 100}%` }}
                    >
                      <input
                        id="volume-slider"
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={draftVolume}
                        onChange={(e) => setDraftVolume(parseFloat(e.target.value))}
                        aria-label="Master volume"
                      />
                      <span className="settings-volume-value">{Math.round(draftVolume * 100)}%</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "game" && (
            <div className="settings-section">
              <div className="settings-fields">
                <h4 className="settings-fields-heading">Game</h4>
                <SegmentedControl
                  label="Brush cursor style"
                  showLabel
                  hint="Choose whether the brush shows a crosshair or a circular outline matching brush size."
                  value={draftBrushCursor}
                  options={BRUSH_CURSOR_OPTIONS}
                  onChange={setDraftBrushCursor}
                />

                <Switch
                  label="Confetti celebration effects"
                  hint="Enable celebratory particle confetti bursts on correct guesses and victory reveals."
                  checked={draftConfettiEffects}
                  onChange={setDraftConfettiEffects}
                />
              </div>
            </div>
          )}

          {activeTab === "shortcuts" && (
            <div className="settings-section">
              <div className="settings-section-header">
                <div>
                  <h4>Keyboard shortcuts</h4>
                  <p className="settings-description">
                    Click on a shortcut badge to rebind it. Press <kbd>Esc</kbd> to cancel.
                  </p>
                </div>
                <button
                  type="button"
                  className="reset-defaults-button"
                  onClick={handleResetDefaults}
                  title="Reset shortcuts to original defaults"
                >
                  Reset to defaults
                </button>
              </div>

              <div className="keybindings-grid">
                {actionKeys.map((action) => {
                  const keys = draftKeyBindings[action] || [];
                  const defaultKeys = DEFAULT_KEY_BINDINGS[action] || [];

                  return (
                    <div key={action} className="keybinding-row">
                      <span className="keybinding-icon" aria-hidden="true">{ACTION_ICONS[action]}</span>
                      <span className="keybinding-label">{ACTION_LABELS[action]}</span>
                      <div className="keybinding-badges">
                        {/* Primary Key Slot */}
                        <button
                          type="button"
                          className={`kbd-badge${
                            activeRebind?.action === action && activeRebind.slotIndex === 0
                              ? " rebinding"
                              : ""
                          }`}
                          onClick={() => setActiveRebind({ action, slotIndex: 0 })}
                          title="Click to rebind primary key"
                        >
                          {activeRebind?.action === action && activeRebind.slotIndex === 0
                            ? "Press key..."
                            : keys[0]
                            ? formatKey(keys[0])
                            : "None"}
                        </button>

                        {/* Secondary Key Slot (if default had secondary key, or for tool actions) */}
                        {(defaultKeys.length > 1 || keys.length > 1) && (
                          <button
                            type="button"
                            className={`kbd-badge secondary${
                              activeRebind?.action === action && activeRebind.slotIndex === 1
                                ? " rebinding"
                                : ""
                            }`}
                            onClick={() => setActiveRebind({ action, slotIndex: 1 })}
                            title="Click to rebind secondary key"
                          >
                            {activeRebind?.action === action && activeRebind.slotIndex === 1
                              ? "Press key..."
                              : keys[1]
                              ? formatKey(keys[1])
                              : "+ key"}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        </div>

        <div className="settings-modal-footer">
          {saveError && <p className="auth-error" role="alert">{saveError}</p>}
          <button type="button" className="modal-button secondary" onClick={handleDiscard} disabled={saving}>
            Discard
          </button>
          <button type="button" className="modal-button" onClick={() => void handleSave()} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {authMode && (
        <AuthDialog
          mode={authMode}
          suggestedUsername={isGuest ? (authUser?.displayName ?? "") : ""}
          onClose={() => setAuthMode(null)}
          onSwitchMode={setAuthMode}
          onSubmit={authMode === "login" ? login : register}
        />
      )}
    </div>
  );
}

export function SettingsModal() {
  const isSettingsOpen = useSettingsStore((s) => s.isSettingsOpen);
  // A login performed from inside the dialog can replace the browser's values
  // with the registered account's copy. Keying the draft editor to that
  // durable snapshot remounts it with the new values without synchronously
  // cascading local state updates from an effect.
  const settingsSnapshot = useSettingsStore((s) =>
    JSON.stringify({
      keyBindings: s.keyBindings,
      brushCursor: s.brushCursor,
      theme: s.theme,
      confettiEffects: s.confettiEffects,
      soundEffects: s.soundEffects,
      volume: s.volume,
      colorblindSafeColors: s.colorblindSafeColors,
      autoClearChatOnGuess: s.autoClearChatOnGuess,
      customBrushPresets: s.customBrushPresets,
      nameColor: s.nameColor,
    }),
  );
  if (!isSettingsOpen) return null;
  return <SettingsModalContent key={settingsSnapshot} />;
}
