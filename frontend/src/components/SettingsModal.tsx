import { useEffect, useState } from "react";
import { SettingsIcon } from "./SettingsIcon";
import {
  ACTION_LABELS,
  DEFAULT_KEY_BINDINGS,
  type KeyBindings,
  type PenCursorStyle,
  useSettingsStore,
} from "../store/settingsStore";

type SettingsTab = "general" | "game" | "shortcuts";

const TABS: { id: SettingsTab; label: string }[] = [
  { id: "general", label: "General" },
  { id: "game", label: "Game" },
  { id: "shortcuts", label: "Keyboard Shortcuts" },
];

function formatKey(key: string): string {
  if (key === " ") return "Space";
  if (key.length === 1) return key.toUpperCase();
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function SettingsModalContent() {
  const { closeSettings, keyBindings, penCursor, theme, confettiEffects, soundEffects, volume, setAllSettings } =
    useSettingsStore();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [draftKeyBindings, setDraftKeyBindings] = useState<KeyBindings>(keyBindings);
  const [draftPenCursor, setDraftPenCursor] = useState<PenCursorStyle>(penCursor);
  const [draftTheme, setDraftTheme] = useState<import("../store/settingsStore").AppTheme>(theme);
  const [draftConfettiEffects, setDraftConfettiEffects] = useState<boolean>(confettiEffects);
  const [draftSoundEffects, setDraftSoundEffects] = useState<boolean>(soundEffects);
  const [draftVolume, setDraftVolume] = useState<number>(volume);
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
    });
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
              <h4>Appearance</h4>
              <div className="settings-field" style={{ marginTop: "12px" }}>
                <label htmlFor="theme-select" className="settings-label">
                  Theme
                </label>
                <select
                  id="theme-select"
                  className="settings-select"
                  value={draftTheme}
                  onChange={(e) => setDraftTheme(e.target.value as import("../store/settingsStore").AppTheme)}
                >
                  <option value="light">Light Theme</option>
                  <option value="dark">Dark Theme</option>
                </select>
                <p className="settings-description" style={{ marginTop: "6px" }}>
                  First-time visits follow your device preference. Choose a theme here to save your own preference.
                </p>
              </div>

              <h4 style={{ marginTop: "24px" }}>Audio & Sound Settings</h4>
              <div className="settings-field" style={{ marginTop: "12px" }}>
                <label htmlFor="sound-effects-toggle" className="settings-label" style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                  <input
                    id="sound-effects-toggle"
                    type="checkbox"
                    checked={draftSoundEffects}
                    onChange={(e) => setDraftSoundEffects(e.target.checked)}
                  />
                  <span>Sound Effects 🔊</span>
                </label>
                <p className="settings-description" style={{ marginTop: "6px" }}>
                  Enable Web Audio chimes for guesses, round start, timer warnings, and player events.
                </p>
              </div>

              {draftSoundEffects && (
                <div className="settings-field" style={{ marginTop: "16px" }}>
                  <label htmlFor="volume-slider" className="settings-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>Master Volume</span>
                    <span style={{ fontWeight: 600, color: "#2563eb" }}>{Math.round(draftVolume * 100)}%</span>
                  </label>
                  <input
                    id="volume-slider"
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={draftVolume}
                    onChange={(e) => setDraftVolume(parseFloat(e.target.value))}
                    style={{ width: "100%", marginTop: "8px" }}
                  />
                </div>
              )}
            </div>
          )}

          {activeTab === "game" && (
            <div className="settings-section">
              <h4>Game Settings</h4>
              <div className="settings-field" style={{ marginTop: "12px" }}>
                <label htmlFor="pen-cursor-style" className="settings-label">
                  Pen Cursor Style
                </label>
                <select
                  id="pen-cursor-style"
                  className="settings-select"
                  value={draftPenCursor}
                  onChange={(e) => setDraftPenCursor(e.target.value as PenCursorStyle)}
                >
                  <option value="crosshair">Default Crosshair</option>
                  <option value="circle">Circular Outline (matching brush size)</option>
                </select>
                <p className="settings-description" style={{ marginTop: "6px" }}>
                  Choose whether the pen tool displays the default crosshair or a circular outline showing its field of action.
                </p>
              </div>

              <div className="settings-field" style={{ marginTop: "16px" }}>
                <label htmlFor="confetti-effects-toggle" className="settings-label" style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                  <input
                    id="confetti-effects-toggle"
                    type="checkbox"
                    checked={draftConfettiEffects}
                    onChange={(e) => setDraftConfettiEffects(e.target.checked)}
                  />
                  <span>Confetti Celebration Effects 🎉</span>
                </label>
                <p className="settings-description" style={{ marginTop: "6px" }}>
                  Enable celebratory particle confetti bursts on correct guesses and victory reveals.
                </p>
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
