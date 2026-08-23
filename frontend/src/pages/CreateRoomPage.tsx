import { useEffect, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CustomPromptsEditor } from "../components/CustomPromptsEditor";
import { PromptListPicker } from "../components/PromptListPicker";
import {
  ChoiceChips,
  InputNumber,
  SegmentedControl,
  Switch,
  ToggleChips,
} from "../components/RoomSetupControls";
import {
  COLOR_MODE_OPTIONS,
  DEFAULT_ALLOWED_TOOLS,
  DEFAULT_COLOR_MODE,
  TOOL_GROUP_OPTIONS,
  canDisallowTool,
} from "../lib/drawingRules";
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
import { sessionFrom } from "../lib/roomEntryState";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, ColorMode, DrawingToolGroup, HintMode, ScoringMode } from "../types";
import { AccountMenu } from "../components/AccountMenu";
import { currentPlayerName, useAuthStore } from "../store/authStore";
import {
  createRoomPreset,
  deleteRoomPreset,
  getMyRoomPresets,
  getRoomPreset,
  updateRoomPreset,
  type RoomPresetSettings,
  type RoomPresetSummary,
} from "../lib/roomPresets";

export function CreateRoomPage() {
  const navigate = useNavigate();
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const colorblindSafeColors = useSettingsStore((state) => state.colorblindSafeColors);
  const authUser = useAuthStore((state) => state.user);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [persistent, setPersistent] = useState(false);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [rounds, setRounds] = useState(3);
  const [drawingSeconds, setDrawingSeconds] = useState(DEFAULT_DRAWING_SECONDS);
  const [promptListSlugs, setPromptListSlugs] = useState<string[]>(["english_standard"]);
  const [promptListShareCodes, setPromptListShareCodes] = useState<string[]>([]);
  const [customPrompts, dispatchCustomPrompts] = useReducer(
    customPromptsReducer,
    undefined,
    () => createCustomPromptsState(),
  );
  const [hintMode, setHintMode] = useState<HintMode>(DEFAULT_HINT_MODE);
  const [scoringMode, setScoringMode] = useState<ScoringMode>("default");
  const [spectatorsSeePrompt, setSpectatorsSeePrompt] = useState(false);
  const [hideMaskedPrompt, setHideMaskedPrompt] = useState(false);
  const [allowedTools, setAllowedTools] = useState<DrawingToolGroup[]>(DEFAULT_ALLOWED_TOOLS);
  const [colorMode, setColorMode] = useState<ColorMode>(DEFAULT_COLOR_MODE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [presets, setPresets] = useState<RoomPresetSummary[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!authUser || authUser.isAnonymous) {
      return;
    }
    void getMyRoomPresets()
      .then((value) => {
        if (!cancelled) setPresets(value);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your room presets.");
      });
    return () => { cancelled = true; };
  }, [authUser]);

  function currentPresetSettings(): RoomPresetSettings {
    return {
      name: roomName.trim(),
      isPublic,
      maxPlayers,
      rounds,
      drawingSeconds,
      customPrompts: "",
      customPromptsOnly: false,
      hintMode,
      scoringMode,
      spectatorsSeePrompt,
      hideMaskedPrompt,
      allowedTools,
      colorMode,
      promptListSlugs,
      promptListShareCodes: [],
    };
  }

  function applySettings(settings: RoomPresetSettings) {
    setRoomName(settings.name);
    setIsPublic(settings.isPublic);
    setMaxPlayers(settings.maxPlayers);
    setRounds(settings.rounds);
    setDrawingSeconds(settings.drawingSeconds);
    setHintMode(settings.hintMode);
    setScoringMode(settings.scoringMode);
    setSpectatorsSeePrompt(settings.spectatorsSeePrompt);
    setHideMaskedPrompt(settings.hideMaskedPrompt);
    setAllowedTools(settings.allowedTools);
    setColorMode(settings.colorMode);
    setPromptListSlugs(settings.promptListSlugs);
    setPromptListShareCodes([]);
    dispatchCustomPrompts({ type: "reset", value: "", only: false });
  }

  async function refreshPresets(preferredId = selectedPresetId) {
    const value = await getMyRoomPresets();
    setPresets(value);
    if (preferredId && value.some((preset) => preset.id === preferredId)) {
      setSelectedPresetId(preferredId);
    } else if (preferredId) {
      setSelectedPresetId("");
    }
  }

  async function handleApplyPreset() {
    if (!selectedPresetId) return;
    setPresetBusy(true);
    setError(null);
    try {
      const preset = await getRoomPreset(selectedPresetId);
      applySettings(preset.settings);
      setPresetName(preset.name);
    } catch (presetError) {
      setError(presetError instanceof Error ? presetError.message : "Could not apply that preset.");
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleSavePreset() {
    if (!presetName.trim()) {
      setError("Enter a name for the room preset.");
      return;
    }
    setPresetBusy(true);
    setError(null);
    try {
      const created = await createRoomPreset(presetName, currentPresetSettings());
      await refreshPresets(created.id);
      setPresetName(created.name);
    } catch (presetError) {
      setError(presetError instanceof Error ? presetError.message : "Could not save that preset.");
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleUpdatePreset() {
    const selected = presets.find((preset) => preset.id === selectedPresetId);
    if (!selected) return;
    setPresetBusy(true);
    setError(null);
    try {
      const updated = await updateRoomPreset(
        selected.id,
        selected.version,
        presetName.trim() ? presetName : selected.name,
        currentPresetSettings(),
      );
      await refreshPresets(updated.id);
      setPresetName(updated.name);
    } catch (presetError) {
      setError(presetError instanceof Error ? presetError.message : "Could not update that preset.");
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleDeletePreset() {
    if (!selectedPresetId) return;
    if (!window.confirm("Delete this room-setting preset?")) return;
    setPresetBusy(true);
    setError(null);
    try {
      await deleteRoomPreset(selectedPresetId);
      await refreshPresets("");
      setSelectedPresetId("");
      setPresetName("");
    } catch (presetError) {
      setError(presetError instanceof Error ? presetError.message : "Could not delete that preset.");
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleCreate() {
    if (customPrompts.analysis.hasErrors) {
      setError("Fix the custom-prompt entries marked above before creating the room.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("create_room", {
        nickname: currentPlayerName(), nameColor, colorblindSafeColors, name: roomName.trim(), isPublic, persistent, maxPlayers, rounds, drawingSeconds,
        customPrompts: customPrompts.value.trim(), customPromptsOnly: customPrompts.only, hintMode, scoringMode,
        spectatorsSeePrompt, hideMaskedPrompt, allowedTools, colorMode, promptListSlugs,
        promptListShareCodes,
      });
      const session = sessionFrom(response);
      if (session) {
        setSession(session);
        navigate(`/room/${session.code}`);
        return;
      }
      setError(response.error || "Failed to create room");
    } catch (createError) {
      setError(socketRequestErrorMessage(createError, "create the room"));
    } finally {
      setBusy(false);
    }
  }

  const hintsDisabled = hideMaskedPrompt || scoringMode === "none";

  function handleCustomPromptsChange(value: string) {
    dispatchCustomPrompts({ type: "change", value });
  }

  return <main className="create-room-page">
    <div className="create-room-top-bar">
      <button type="button" className="back-link" onClick={() => navigate("/")}>← Back to lobby</button>
      <AccountMenu />
    </div>
    <section className="create-room-card">
      <div className="create-room-heading"><p>Room setup</p><h1>Create a room</h1></div>
      {error && <p className="create-room-error" role="alert">{error}</p>}
      {authUser && !authUser.isAnonymous && (
        <section className="room-preset-panel" aria-labelledby="room-preset-heading">
          <div>
            <h2 id="room-preset-heading">Room-setting presets</h2>
            <p>Reuse configuration for a new ordinary room. Presets never reuse a room code, members, scores, or live state.</p>
          </div>
          <div className="room-preset-controls">
            <label>
              Saved preset
              <select
                value={selectedPresetId}
                onChange={(event) => {
                  const id = event.target.value;
                  setSelectedPresetId(id);
                  setPresetName(presets.find((preset) => preset.id === id)?.name || "");
                }}
              >
                <option value="">Choose a preset</option>
                {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
              </select>
            </label>
            <button type="button" disabled={!selectedPresetId || presetBusy} onClick={() => void handleApplyPreset()}>Apply</button>
            <label>
              Preset name
              <input type="text" value={presetName} maxLength={64} onChange={(event) => setPresetName(event.target.value)} />
            </label>
            <button type="button" disabled={presetBusy || !presetName.trim() || customPrompts.analysis.usableCount > 0 || promptListShareCodes.length > 0} onClick={() => void handleSavePreset()}>Save new</button>
            <button type="button" disabled={!selectedPresetId || presetBusy || customPrompts.analysis.usableCount > 0 || promptListShareCodes.length > 0} onClick={() => void handleUpdatePreset()}>Update</button>
            <button type="button" className="room-preset-delete" disabled={!selectedPresetId || presetBusy} onClick={() => void handleDeletePreset()}>Delete</button>
          </div>
          {(customPrompts.analysis.usableCount > 0 || promptListShareCodes.length > 0) && <p className="setting-dependency">Save custom prompts as your own prompt list and remove shared-list codes before saving a preset.</p>}
        </section>
      )}
      <div className="create-room-basic-grid">
        <Switch
          label="Keep this room for future games"
          hint={authUser && !authUser.isAnonymous
            ? "The code and settings stay with your account. Quick custom prompts must be saved as a prompt list first."
            : "Create an account to own a persistent room."}
          checked={persistent}
          disabled={!authUser || authUser.isAnonymous || customPrompts.analysis.usableCount > 0}
          onChange={setPersistent}
        />
        <div className="create-room-name-row">
          <label className="create-room-name-field">
            Room name (optional)
            {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
            <input type="search" inputMode="text" value={roomName} onChange={(event) => setRoomName(event.target.value)} maxLength={40} placeholder="Leave blank for a random name!" autoComplete="off" autoCapitalize="sentences" spellCheck={true} enterKeyHint="done" />
          </label>
          <SegmentedControl
            label="Visibility"
            value={isPublic ? "public" : "private"}
            onChange={(value) => setIsPublic(value === "public")}
            options={[
              { value: "public", label: "Public" },
              { value: "private", label: "Private" },
            ]}
          />
        </div>
        <InputNumber label="Max players" value={maxPlayers} min={MAX_PLAYERS_MIN} max={MAX_PLAYERS_MAX} onChange={setMaxPlayers} />
        <InputNumber label="Rounds" value={rounds} min={ROUNDS_MIN} max={ROUNDS_MAX} onChange={setRounds} />
        <InputNumber label="Drawing time (seconds)" value={drawingSeconds} options={DRAWING_TIME_OPTIONS} onChange={setDrawingSeconds} />
        <PromptListPicker
          selectedSlugs={promptListSlugs}
          onChange={setPromptListSlugs}
          shareCodes={promptListShareCodes}
          onShareCodesChange={setPromptListShareCodes}
        />
        <ToggleChips
          label="Allowed tools"
          values={allowedTools}
          onChange={setAllowedTools}
          options={TOOL_GROUP_OPTIONS.map((option) => ({
            ...option,
            disabled: !canDisallowTool(option.value, allowedTools),
          }))}
        />
        <ChoiceChips label="Colors" value={colorMode} onChange={setColorMode} options={COLOR_MODE_OPTIONS} />
      </div>
      <details className="advanced-settings"><summary>Advanced settings <span>Spectators, scoring, hints, and custom prompts</span></summary>
        <div className="advanced-settings-content">
          <Switch label="Allow spectators to see the prompt" checked={spectatorsSeePrompt} onChange={setSpectatorsSeePrompt} />
          <Switch
            label="Hide blanks"
            checked={hideMaskedPrompt}
            onChange={(checked) => {
              setHideMaskedPrompt(checked);
              if (checked) setHintMode("none");
            }}
          />
          <ChoiceChips
            label="Scoring"
            value={scoringMode}
            onChange={(mode) => {
              setScoringMode(mode);
              if (mode === "none" && (hintMode === "purchase" || hintMode === "wheel")) setHintMode("none");
            }}
            options={SCORING_OPTIONS}
          />
          <ChoiceChips
            label="Hints"
            value={hintMode}
            disabled={hideMaskedPrompt}
            onChange={setHintMode}
            options={HINT_OPTIONS.map((option) => ({
              ...option,
              disabled: scoringMode === "none" && (option.value === "purchase" || option.value === "wheel"),
            }))}
          />
          {hideMaskedPrompt && <p className="setting-dependency">Hints are off because blanks are hidden.</p>}
          {hintsDisabled && !hideMaskedPrompt && <p className="setting-dependency">Point-purchase hint modes require scoring.</p>}
          {persistent ? (
            <p className="setting-dependency">Persistent rooms use saved prompt lists; quick custom prompts are never stored in room configuration.</p>
          ) : (
            <CustomPromptsEditor
              value={customPrompts.value}
              analysis={customPrompts.analysis}
              onChange={handleCustomPromptsChange}
              footer={authUser && !authUser.isAnonymous && customPrompts.analysis.usableCount > 0 && !customPrompts.analysis.hasErrors ? (
                <button
                  type="button"
                  className="custom-prompts-apply"
                  onClick={() => navigate("/my-prompt-lists", { state: { quickPrompts: customPrompts.value } })}
                >
                  Save as reusable list
                </button>
              ) : undefined}
            />
          )}
          <Switch
            label="Only use custom prompts"
            hint="Add a usable custom prompt to enable this option."
            checked={customPrompts.only}
            disabled={persistent || customPrompts.analysis.usableCount === 0 || customPrompts.analysis.hasErrors}
            onChange={(only) => dispatchCustomPrompts({ type: "set-only", only })}
          />
        </div>
      </details>
      <button type="button" className="create-room-submit" disabled={busy || customPrompts.analysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </section>
  </main>;
}
