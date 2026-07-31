import { useEffect, useState } from "react";
import { SettingsIcon } from "./SettingsIcon";
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

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [draftKeyBindings, setDraftKeyBindings] = useState<KeyBindings>(keyBindings);
  const [draftPenCursor, setDraftPenCursor] = useState<PenCursorStyle>(penCursor);
  const [draftTheme, setDraftTheme] = useState<AppTheme>(theme);
  const [draftConfettiEffects, setDraftConfettiEffects] = useState<boolean>(confettiEffects);
  const [draftSoundEffects, setDraftSoundEffects] = useState<boolean>(soundEffects);
  const [draftVolume, setDraftVolume] = useState<number>(volume);
  const [draftNameColor, setDraftNameColor] = useState<string>(nameColor);
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

  const handleSave = () => {
    setAllSettings({
      keyBindings: draftKeyBindings,
      penCursor: draftPenCursor,
      theme: draftTheme,
      confettiEffects: draftConfettiEffects,
      soundEffects: draftSoundEffects,
      volume: draftVolume,
      nameColor: draftNameColor,
    });
    socket.emit("update_player_settings", { nameColor: draftNameColor });
    closeSettings();
  };

  const handleResetDefaults = () => {
    setDraftKeyBindings(DEFAULT_KEY_BINDINGS);
    setActiveRebind(null);
  };

  const actionKeys = Object.keys(ACTION_LABELS) as (keyof KeyBindings)[];

  return (
    <div className="modal-overlay" onClick={handleDiscard}>
      <div
        className="modal-card settings-modal-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Settings"
      >
        <div className="settings-modal-header">
          <h3 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <SettingsIcon size={20} />
            <span>Settings</span>
          </h3>
          <button type="button" className="close-icon-button" onClick={handleDiscard} title="Close">
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
                <h4 className="settings-fields-heading">Appearance</h4>
                <SegmentedControl
                  label="Theme"
                  showLabel
                  hint="Follow your device preference, or lock Light / Dark."
                  value={draftTheme}
                  options={THEME_OPTIONS}
                  onChange={setDraftTheme}
                />

                <div className="settings-labeled-field name-color-setting">
                  <span className="settings-labeled-field-label">
                    Player name color
                    <FieldHint hint="This color is visible to everyone in rooms you join." />
                  </span>
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
                </div>

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
          <button type="button" className="modal-button" onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export function SettingsModal() {
  const isSettingsOpen = useSettingsStore((s) => s.isSettingsOpen);
  if (!isSettingsOpen) return null;
  return <SettingsModalContent />;
}
