import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CustomWordsEditor } from "../components/CustomWordsEditor";
import {
  ChoiceChips,
  InputNumber,
  SegmentedControl,
  Switch,
} from "../components/RoomSetupControls";
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
import { analyzeCustomWords } from "../lib/customWords";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, HintMode, ScoringMode } from "../types";

export function CreateRoomPage() {
  const navigate = useNavigate();
  const nickname = useGameStore((state) => state.nickname);
  const setSession = useGameStore((state) => state.setSession);
  const nameColor = useSettingsStore((state) => state.nameColor);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [rounds, setRounds] = useState(3);
  const [drawingSeconds, setDrawingSeconds] = useState(DEFAULT_DRAWING_SECONDS);
  const [customWords, setCustomWords] = useState("");
  const [customWordsOnly, setCustomWordsOnly] = useState(false);
  const [hintMode, setHintMode] = useState<HintMode>(DEFAULT_HINT_MODE);
  const [scoringMode, setScoringMode] = useState<ScoringMode>("default");
  const [spectatorsSeeSolution, setSpectatorsSeeSolution] = useState(false);
  const [hideMaskedPrompt, setHideMaskedPrompt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const wordAnalysis = analyzeCustomWords(customWords);

  async function handleCreate() {
    const trimmedNickname = nickname.trim();
    if (!trimmedNickname) {
      navigate("/");
      return;
    }
    if (wordAnalysis.hasErrors) {
      setError("Fix the custom-word entries marked above before creating the room.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("create_room", {
        nickname: trimmedNickname, nameColor, name: roomName.trim(), isPublic, maxPlayers, rounds, drawingSeconds,
        customWords: customWords.trim(), customWordsOnly, hintMode, scoringMode,
        spectatorsSeeSolution, hideMaskedPrompt,
      });
      if (response.ok && response.roomId && response.code && response.token) {
        setSession({ roomId: response.roomId, code: response.code, token: response.token });
        navigate(`/room/${response.code}`);
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

  function handleCustomWordsChange(value: string) {
    setCustomWords(value);
    const analysis = analyzeCustomWords(value);
    if (analysis.usableCount === 0 || analysis.hasErrors) setCustomWordsOnly(false);
  }

  return <main className="create-room-page">
    <button type="button" className="back-link" onClick={() => navigate("/")}>← Back to lobby</button>
    <section className="create-room-card">
      <div className="create-room-heading"><p>Room setup</p><h1>Create a room</h1></div>
      {error && <p className="create-room-error" role="alert">{error}</p>}
      <div className="create-room-basic-grid">
        <div className="create-room-name-row">
          <label className="create-room-name-field">Room name (optional)<input type="search" value={roomName} onChange={(event) => setRoomName(event.target.value)} maxLength={40} placeholder="Leave blank for a random name!" autoComplete="off" /></label>
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
      </div>
      <details className="advanced-settings"><summary>Advanced settings <span>Spectators, scoring, hints, and custom words</span></summary>
        <div className="advanced-settings-content">
          <Switch label="Allow spectators to see the prompt" checked={spectatorsSeeSolution} onChange={setSpectatorsSeeSolution} />
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
          <CustomWordsEditor value={customWords} onChange={handleCustomWordsChange} />
          <Switch
            label="Only use custom words"
            hint="Add a usable custom word to enable this option."
            checked={customWordsOnly}
            disabled={wordAnalysis.usableCount === 0 || wordAnalysis.hasErrors}
            onChange={setCustomWordsOnly}
          />
        </div>
      </details>
      <button type="button" className="create-room-submit" disabled={busy || wordAnalysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </section>
  </main>;
}
