import { useEffect, useState } from "react";
import { CustomWordsEditor } from "./CustomWordsEditor";
import {
  ChoiceChips,
  DEFAULT_DRAWING_SECONDS,
  DEFAULT_HINT_MODE,
  DRAWING_TIME_OPTIONS,
  HINT_OPTIONS,
  InputNumber,
  MAX_PLAYERS_MAX,
  MAX_PLAYERS_MIN,
  ROUNDS_MAX,
  ROUNDS_MIN,
  SCORING_OPTIONS,
  SegmentedControl,
  Switch,
} from "./RoomSetupControls";
import { analyzeCustomWords } from "../lib/customWords";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, EditableRoomSettings, HintMode, ScoringMode } from "../types";

const emptySettings: EditableRoomSettings = {
  name: "",
  isPublic: true,
  maxPlayers: 8,
  rounds: 3,
  drawingSeconds: DEFAULT_DRAWING_SECONDS,
  customWords: "",
  customWordsOnly: false,
  hintMode: DEFAULT_HINT_MODE,
  scoringMode: "default",
  spectatorsSeeSolution: false,
  hideMaskedPrompt: false,
};

export function RoomSettingsEditor() {
  const [settings, setSettings] = useState<EditableRoomSettings>(emptySettings);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const analysis = analyzeCustomWords(settings.customWords);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await emitWithAck<{ ok: boolean; error?: string; settings?: EditableRoomSettings }>("get_room_settings", {});
        if (cancelled) return;
        if (response.ok && response.settings) setSettings(response.settings);
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
    if (analysis.hasErrors) { setError("Fix custom-word errors before saving."); return; }
    setBusy(true); setError(null);
    try {
      const response = await emitWithAck<AckResponse>("update_room_settings", settings);
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
        <label className="create-room-name-field">Room name<input value={settings.name} onChange={(event) => update({ name: event.target.value })} maxLength={40} /></label>
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
        <CustomWordsEditor value={settings.customWords} onChange={(customWords) => update({ customWords, customWordsOnly: analyzeCustomWords(customWords).usableCount > 0 && !analyzeCustomWords(customWords).hasErrors ? settings.customWordsOnly : false })} />
        <Switch
          label="Only use custom words"
          hint="Add a usable custom word to enable this option."
          checked={settings.customWordsOnly}
          disabled={analysis.usableCount === 0 || analysis.hasErrors}
          onChange={(customWordsOnly) => update({ customWordsOnly })}
        />
      </div></details>
    </div>}
    {error && <p className="create-room-error" role="alert">{error}</p>}
    <div className="room-settings-save"><button type="button" className="room-settings-save-button" disabled={loading || busy || analysis.hasErrors} onClick={() => void save()}>{busy ? "Saving…" : "Save settings"}</button></div>
  </section>;
}
