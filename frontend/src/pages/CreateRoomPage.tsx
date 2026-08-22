import { useReducer, useState } from "react";
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
import { currentPlayerName } from "../store/authStore";

export function CreateRoomPage() {
  const navigate = useNavigate();
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const colorblindSafeColors = useSettingsStore((state) => state.colorblindSafeColors);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [rounds, setRounds] = useState(3);
  const [drawingSeconds, setDrawingSeconds] = useState(DEFAULT_DRAWING_SECONDS);
  const [promptListSlugs, setPromptListSlugs] = useState<string[]>(["english_standard"]);
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

  async function handleCreate() {
    if (customPrompts.analysis.hasErrors) {
      setError("Fix the custom-prompt entries marked above before creating the room.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("create_room", {
        nickname: currentPlayerName(), nameColor, colorblindSafeColors, name: roomName.trim(), isPublic, maxPlayers, rounds, drawingSeconds,
        customPrompts: customPrompts.value.trim(), customPromptsOnly: customPrompts.only, hintMode, scoringMode,
        spectatorsSeePrompt, hideMaskedPrompt, allowedTools, colorMode, promptListSlugs,
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
      <div className="create-room-basic-grid">
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
        <PromptListPicker selectedSlugs={promptListSlugs} onChange={setPromptListSlugs} />
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
          <CustomPromptsEditor value={customPrompts.value} analysis={customPrompts.analysis} onChange={handleCustomPromptsChange} />
          <Switch
            label="Only use custom prompts"
            hint="Add a usable custom prompt to enable this option."
            checked={customPrompts.only}
            disabled={customPrompts.analysis.usableCount === 0 || customPrompts.analysis.hasErrors}
            onChange={(only) => dispatchCustomPrompts({ type: "set-only", only })}
          />
        </div>
      </details>
      <button type="button" className="create-room-submit" disabled={busy || customPrompts.analysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </section>
  </main>;
}
