import { useEffect, useState } from "react";
import { CustomWordsEditor } from "./CustomWordsEditor";
import { analyzeCustomWords } from "../lib/customWords";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, EditableRoomSettings, HintMode, ScoringMode } from "../types";

const emptySettings: EditableRoomSettings = { name: "", isPublic: true, maxPlayers: 8, rounds: 3, drawingSeconds: 80, customWords: "", customWordsOnly: false, hintMode: "none", scoringMode: "default", spectatorsSeeSolution: false, hideMaskedPrompt: false };

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
      <label>Room name<input value={settings.name} onChange={(event) => update({ name: event.target.value })} maxLength={40} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={settings.isPublic} onChange={(event) => update({ isPublic: event.target.checked })} />Public (listed below)</label>
      <label>Max players<input type="number" min={2} max={12} value={settings.maxPlayers} onChange={(event) => update({ maxPlayers: Number(event.target.value) })} /></label>
      <label>Rounds<input type="number" min={1} max={10} value={settings.rounds} onChange={(event) => update({ rounds: Number(event.target.value) })} /></label>
      <label>Drawing time (seconds)<input type="number" min={15} max={240} value={settings.drawingSeconds} onChange={(event) => update({ drawingSeconds: Number(event.target.value) })} /></label>
      <details><summary>Advanced settings</summary><div className="room-settings-advanced">
        <label>Scoring<select value={settings.scoringMode} onChange={(event) => { const scoringMode = event.target.value as ScoringMode; update({ scoringMode, hintMode: scoringMode === "none" && ["purchase", "wheel"].includes(settings.hintMode) ? "none" : settings.hintMode }); }}><option value="default">Default scoring</option><option value="none">No scoring</option></select></label>
        <label>Hint letters<select value={settings.hintMode} disabled={settings.hideMaskedPrompt} onChange={(event) => update({ hintMode: event.target.value as HintMode })}><option value="none">Off</option><option value="checkpoints">Timed hints</option><option value="purchase" disabled={settings.scoringMode === "none"}>Buyable hints</option><option value="wheel" disabled={settings.scoringMode === "none"}>Buy full letters</option></select></label>
        {settings.hideMaskedPrompt && <p className="setting-dependency">Hints are off because the masked prompt is hidden.</p>}
        <label className="checkbox-label"><input type="checkbox" checked={settings.spectatorsSeeSolution} onChange={(event) => update({ spectatorsSeeSolution: event.target.checked })} />Allow spectators to see the word</label>
        <label className="checkbox-label"><input type="checkbox" checked={settings.hideMaskedPrompt} onChange={(event) => update({ hideMaskedPrompt: event.target.checked, hintMode: event.target.checked ? "none" : settings.hintMode })} />Always hide the masked prompt from guessers</label>
        <CustomWordsEditor value={settings.customWords} onChange={(customWords) => update({ customWords, customWordsOnly: analyzeCustomWords(customWords).usableCount > 0 && !analyzeCustomWords(customWords).hasErrors ? settings.customWordsOnly : false })} />
        <label className="checkbox-label"><input type="checkbox" checked={settings.customWordsOnly} disabled={analysis.usableCount === 0 || analysis.hasErrors} onChange={(event) => update({ customWordsOnly: event.target.checked })} />Only use custom words</label>
      </div></details>
    </div>}
    {error && <p className="create-room-error" role="alert">{error}</p>}
    <div className="room-settings-save"><button type="button" className="waiting-start-button" disabled={loading || busy || analysis.hasErrors} onClick={() => void save()}>{busy ? "Saving…" : "Save settings"}</button></div>
  </section>;
}
