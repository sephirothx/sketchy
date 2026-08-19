import { useEffect, useId, useRef, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { emitWithAck } from "../lib/socket";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { ApiError } from "../lib/api";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import { SettingsIcon } from "./SettingsIcon";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { FieldHint, SegmentedControl, Switch } from "./RoomSetupControls";
import {
  ACTION_LABELS,
  DEFAULT_KEY_BINDINGS,
  randomNameColor,
  type AppTheme,
  type KeyBindings,
  type PenCursorStyle,
  useSettingsStore,
} from "../store/settingsStore";
import { socket } from "../lib/socket";

type SettingsTab = "general" | "game" | "shortcuts";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "game", label: "Game" },
  { id: "shortcuts", label: "Keyboard Shortcuts" },
];

const THEME_OPTIONS: { value: AppTheme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

const BRUSH_CURSOR_OPTIONS: { value: PenCursorStyle; label: string }[] = [
  { value: "crosshair", label: "Crosshair" },
  { value: "circle", label: "Outline" },
];

function formatKey(key: string): string {
  if (key === " ") return "Space";
  if (key.length === 1) return key.toUpperCase();
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function SettingsModalContent() {
  const { closeSettings, keyBindings, penCursor, theme, confettiEffects, soundEffects, volume, nameColor, setAllSettings } =
    useSettingsStore();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [draftKeyBindings, setDraftKeyBindings] = useState<KeyBindings>(keyBindings);
  const [draftPenCursor, setDraftPenCursor] = useState<PenCursorStyle>(penCursor);
  const [draftTheme, setDraftTheme] = useState<AppTheme>(theme);
  const [draftConfettiEffects, setDraftConfettiEffects] = useState<boolean>(confettiEffects);
  const [draftSoundEffects, setDraftSoundEffects] = useState<boolean>(soundEffects);
  const [draftVolume, setDraftVolume] = useState<number>(volume);
  const [draftNameColor, setDraftNameColor] = useState<string>(nameColor);
  const authUser = useAuthStore((state) => state.user);
  const setDisplayName = useAuthStore((state) => state.setDisplayName);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const logout = useAuthStore((state) => state.logout);
  const activePlayerId = useGameStore((state) => state.playerId);
  const isGuest = Boolean(authUser?.isAnonymous);
  const [draftName, setDraftName] = useState<string>(authUser?.displayName ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
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
    const trimmedName = draftName.trim();
    const nameChanged = isGuest && trimmedName !== (authUser?.displayName ?? "");
    if (nameChanged) {
      const invalid = nicknameError(trimmedName);
      if (invalid) {
        setNameError(invalid);
        setActiveTab("general");
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
            setNameError(response.error || "Could not change your name.");
            setActiveTab("general");
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
            : "Could not change your name. Please try again.",
        );
        setActiveTab("general");
        return;
      }
    }

    setAllSettings({
      keyBindings: draftKeyBindings,
      penCursor: draftPenCursor,
      theme: draftTheme,
      confettiEffects: draftConfettiEffects,
      soundEffects: draftSoundEffects,
      volume: draftVolume,
      nameColor: draftNameColor,
    });
    // Guests are pinned to the guest grey server-side, so sending a colour
    // would only be rejected.
    if (!isGuest) {
      socket.emit("update_player_settings", { nameColor: draftNameColor });
    }
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
            <SettingsIcon size={20} />
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
            ✕
          </button>
        </div>

        <div className="settings-tabs" role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`settings-tab-button${activeTab === tab.id ? " active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
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
                    Name
                    <FieldHint hint="This is how other players see you." />
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
                        Playing as a guest — your name isn’t saved.
                      </span>
                      <button
                        type="button"
                        className="settings-account-action"
                        onClick={() => setAuthMode("claim")}
                      >
                        Claim your name
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
                    Player name color
                    <FieldHint hint="This color is visible to everyone in rooms you join." />
                  </span>
                  {isGuest ? (
                    /* Guests are pinned to the guest grey server-side. Showing
                       a working picker here would be a control that silently
                       does nothing. */
                    <p className="settings-locked-hint">
                      Guests play in grey. Claim your name to pick a colour.
                    </p>
                  ) : (
                    <div className="name-color-controls">
                      <input
                        id="name-color-input"
                        type="color"
                        value={draftNameColor}
                        onChange={(event) => setDraftNameColor(event.target.value)}
                        aria-label="Player name color"
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
                <SegmentedControl
                  label="Theme"
                  showLabel
                  hint="Follow your device preference, or lock Light / Dark."
                  value={draftTheme}
                  options={THEME_OPTIONS}
                  onChange={setDraftTheme}
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
                  value={draftPenCursor}
                  options={BRUSH_CURSOR_OPTIONS}
                  onChange={setDraftPenCursor}
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
                  <h4>Keyboard Shortcuts</h4>
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
                  Reset Defaults
                </button>
              </div>

              <div className="keybindings-grid">
                {actionKeys.map((action) => {
                  const keys = draftKeyBindings[action] || [];
                  const defaultKeys = DEFAULT_KEY_BINDINGS[action] || [];

                  return (
                    <div key={action} className="keybinding-row">
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

        <div className="settings-modal-footer">
          <button type="button" className="modal-button secondary" onClick={handleDiscard}>
            Discard
          </button>
          <button type="button" className="modal-button" onClick={() => void handleSave()}>
            Save
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
  if (!isSettingsOpen) return null;
  return <SettingsModalContent />;
}
