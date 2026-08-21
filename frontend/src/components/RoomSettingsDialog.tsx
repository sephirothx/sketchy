import { useEffect, useReducer, useState } from "react";
import { CustomPromptsEditor } from "./CustomPromptsEditor";
import { PromptListPicker } from "./PromptListPicker";
import {
  ChoiceChips,
  InputNumber,
  SegmentedControl,
  Switch,
} from "./RoomSetupControls";
import {
  DEFAULT_DRAWING_SECONDS,
  DEFAULT_HINT_MODE,
  DRAWING_TIME_OPTIONS,
  HINT_OPTIONS,
  MAX_PLAYERS_MAX,
  MAX_PLAYERS_MIN,
  ROUNDS_MAX,
  ROUNDS_MIN,
  SCORING_OPTIONS,
} from "../lib/roomSetup";
import { createCustomPromptsState, customPromptsReducer } from "../lib/customPrompts";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, EditableRoomSettings, HintMode, ScoringMode } from "../types";

const emptySettings: EditableRoomSettings = {
  name: "",
  isPublic: true,
  maxPlayers: 8,
  rounds: 3,
  drawingSeconds: DEFAULT_DRAWING_SECONDS,
  customPrompts: "",
  customPromptsOnly: false,
  hintMode: DEFAULT_HINT_MODE,
  scoringMode: "default",
  spectatorsSeeSolution: false,
  hideMaskedPrompt: false,
  promptListSlugs: ["english_standard"],
};

export function RoomSettingsEditor() {
  const [settings, setSettings] = useState<EditableRoomSettings>(emptySettings);
  const [customPrompts, dispatchCustomPrompts] = useReducer(
    customPromptsReducer,
    undefined,
    () => createCustomPromptsState(),
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await emitWithAck<{ ok: boolean; error?: string; settings?: EditableRoomSettings }>("get_room_settings", {});
        if (cancelled) return;
        if (response.ok && response.settings) {
          setSettings(response.settings);
          dispatchCustomPrompts({
            type: "reset",
            value: response.settings.customPrompts,
            only: response.settings.customPromptsOnly,
          });
        }
        else setError(response.error || "Could not load room settings");
      } catch (loadError) {
        if (!cancelled) setError(socketRequestErrorMessage(loadError, "load room settings"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function update(patch: Partial<EditableRoomSettings>) { setSettings((current) => ({ ...current, ...patch })); }
  async function save() {
    if (customPrompts.analysis.hasErrors) { setError("Fix custom-prompt errors before saving."); return; }
    setBusy(true); setError(null);
    try {
      const response = await emitWithAck<AckResponse>("update_room_settings", {
        ...settings,
        customPrompts: customPrompts.value,
        customPromptsOnly: customPrompts.only,
      });
      if (response.ok) setError(null); else setError(response.error || "Could not save room settings");
    } catch (saveError) {
      setError(socketRequestErrorMessage(saveError, "save room settings"));
    } finally {
      setBusy(false);
    }
  }

  return <section className="waiting-card room-settings-editor" aria-labelledby="room-settings-title">
    <div className="room-settings-editor-heading"><p className="waiting-card-kicker">Host settings</p><h2 id="room-settings-title">Edit room settings</h2></div>
    {loading ? <p>Loading settings…</p> : <div className="room-settings-fields">
      <div className="create-room-name-row">
        <label className="create-room-name-field">
          Room name
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
          <input type="search" inputMode="text" value={settings.name} onChange={(event) => update({ name: event.target.value })} maxLength={40} autoComplete="off" autoCapitalize="sentences" spellCheck={true} enterKeyHint="done" />
        </label>
        <SegmentedControl
          label="Visibility"
          value={settings.isPublic ? "public" : "private"}
          onChange={(value) => update({ isPublic: value === "public" })}
          options={[
            { value: "public", label: "Public" },
            { value: "private", label: "Private" },
          ]}
        />
      </div>
      <InputNumber label="Max players" value={settings.maxPlayers} min={MAX_PLAYERS_MIN} max={MAX_PLAYERS_MAX} onChange={(maxPlayers) => update({ maxPlayers })} />
      <InputNumber label="Rounds" value={settings.rounds} min={ROUNDS_MIN} max={ROUNDS_MAX} onChange={(rounds) => update({ rounds })} />
      <InputNumber label="Drawing time (seconds)" value={settings.drawingSeconds} options={DRAWING_TIME_OPTIONS} onChange={(drawingSeconds) => update({ drawingSeconds })} />
      <PromptListPicker
        selectedSlugs={settings.promptListSlugs || ["english_standard"]}
        onChange={(promptListSlugs) => update({ promptListSlugs })}
      />
      <details><summary>Advanced settings</summary><div className="room-settings-advanced">
        <Switch label="Allow spectators to see the prompt" checked={settings.spectatorsSeeSolution} onChange={(spectatorsSeeSolution) => update({ spectatorsSeeSolution })} />
        <Switch
          label="Hide blanks"
          checked={settings.hideMaskedPrompt}
          onChange={(hideMaskedPrompt) => update({ hideMaskedPrompt, hintMode: hideMaskedPrompt ? "none" : settings.hintMode })}
        />
        <ChoiceChips
          label="Scoring"
          value={settings.scoringMode}
          onChange={(scoringMode: ScoringMode) => update({
            scoringMode,
            hintMode: scoringMode === "none" && ["purchase", "wheel"].includes(settings.hintMode) ? "none" : settings.hintMode,
          })}
          options={SCORING_OPTIONS}
        />
        <ChoiceChips
          label="Hints"
          value={settings.hintMode}
          disabled={settings.hideMaskedPrompt}
          onChange={(hintMode: HintMode) => update({ hintMode })}
          options={HINT_OPTIONS.map((option) => ({
            ...option,
            disabled: settings.scoringMode === "none" && (option.value === "purchase" || option.value === "wheel"),
          }))}
        />
        {settings.hideMaskedPrompt && <p className="setting-dependency">Hints are off because blanks are hidden.</p>}
        <CustomPromptsEditor value={customPrompts.value} analysis={customPrompts.analysis} onChange={(value) => dispatchCustomPrompts({ type: "change", value })} />
        <Switch
          label="Only use custom prompts"
          hint="Add a usable custom prompt to enable this option."
          checked={customPrompts.only}
          disabled={customPrompts.analysis.usableCount === 0 || customPrompts.analysis.hasErrors}
          onChange={(only) => dispatchCustomPrompts({ type: "set-only", only })}
        />
      </div></details>
    </div>}
    {error && <p className="create-room-error" role="alert">{error}</p>}
    <div className="room-settings-save"><button type="button" className="room-settings-save-button" disabled={loading || busy || customPrompts.analysis.hasErrors} onClick={() => void save()}>{busy ? "Saving…" : "Save settings"}</button></div>
  </section>;
}
