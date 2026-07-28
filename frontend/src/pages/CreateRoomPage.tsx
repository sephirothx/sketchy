import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CustomWordsEditor } from "../components/CustomWordsEditor";
import { analyzeCustomWords } from "../lib/customWords";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useGameStore } from "../store/gameStore";
import type { AckResponse, HintMode, ScoringMode } from "../types";

export function CreateRoomPage() {
  const navigate = useNavigate();
  const storedNickname = useGameStore((state) => state.nickname);
  const setNickname = useGameStore((state) => state.setNickname);
  const setSession = useGameStore((state) => state.setSession);
  const [nickname, setNicknameInput] = useState(storedNickname);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [maxPlayers, setMaxPlayers] = useState(8);
  const [rounds, setRounds] = useState(3);
  const [drawingSeconds, setDrawingSeconds] = useState(80);
  const [customWords, setCustomWords] = useState("");
  const [customWordsOnly, setCustomWordsOnly] = useState(false);
  const [hintMode, setHintMode] = useState<HintMode>("none");
  const [scoringMode, setScoringMode] = useState<ScoringMode>("default");
  const [spectatorsSeeSolution, setSpectatorsSeeSolution] = useState(false);
  const [hideMaskedPrompt, setHideMaskedPrompt] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const wordAnalysis = analyzeCustomWords(customWords);

  async function handleCreate() {
    const trimmedNickname = nickname.trim();
    if (!trimmedNickname) {
      setError("Enter a nickname before creating a room.");
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
        nickname: trimmedNickname, name: roomName.trim(), isPublic, maxPlayers, rounds, drawingSeconds,
        customWords: customWords.trim(), customWordsOnly, hintMode, scoringMode,
        spectatorsSeeSolution, hideMaskedPrompt,
      });
      if (response.ok && response.roomId && response.code && response.token) {
        setNickname(trimmedNickname);
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
      <div className="create-room-heading"><p>Room setup</p><h1>Create a room</h1><span>Start with the basics; the rest is optional.</span></div>
      {error && <p className="create-room-error" role="alert">{error}</p>}
      <div className="create-room-basic-grid">
        <label>Nickname<input type="search" value={nickname} onChange={(event) => setNicknameInput(event.target.value)} maxLength={20} placeholder="Your name" autoComplete="off" /></label>
        <label>Room name (optional)<input type="search" value={roomName} onChange={(event) => setRoomName(event.target.value)} maxLength={40} placeholder="Leave blank for a random name!" autoComplete="off" /></label>
        <label className="checkbox-label"><input type="checkbox" checked={isPublic} onChange={(event) => setIsPublic(event.target.checked)} />Public (listed below)</label>
        <label>Max players<input type="number" min={2} max={12} value={maxPlayers} onChange={(event) => setMaxPlayers(Number(event.target.value))} /></label>
        <label>Rounds<input type="number" min={1} max={10} value={rounds} onChange={(event) => setRounds(Number(event.target.value))} /></label>
        <label>Drawing time (seconds)<input type="number" min={15} max={240} value={drawingSeconds} onChange={(event) => setDrawingSeconds(Number(event.target.value))} /></label>
      </div>
      <details className="advanced-settings"><summary>Advanced settings <span>Scoring, hints, spectators, and custom words</span></summary>
        <div className="advanced-settings-content">
          <label>Scoring<select value={scoringMode} onChange={(event) => { const mode = event.target.value as ScoringMode; setScoringMode(mode); if (mode === "none" && (hintMode === "purchase" || hintMode === "wheel")) setHintMode("none"); }}><option value="default">Default scoring</option><option value="none">No scoring — just for fun</option></select></label>
          <label>Hint letters<select value={hintMode} disabled={hideMaskedPrompt} onChange={(event) => setHintMode(event.target.value as HintMode)}><option value="none">Off</option><option value="checkpoints">Timed hints, shown to everyone</option><option value="purchase" disabled={scoringMode === "none"}>Players can buy hints with points</option><option value="wheel" disabled={scoringMode === "none"}>Buy full letters, wheel-of-fortune style</option></select></label>
          {hideMaskedPrompt && <p className="setting-dependency">Hints are off because the masked prompt is hidden.</p>}
          {hintsDisabled && !hideMaskedPrompt && <p className="setting-dependency">Point-purchase hint modes require scoring.</p>}
          <label className="checkbox-label"><input type="checkbox" checked={spectatorsSeeSolution} onChange={(event) => setSpectatorsSeeSolution(event.target.checked)} />Allow spectators to see the word</label>
          <label className="checkbox-label"><input type="checkbox" checked={hideMaskedPrompt} onChange={(event) => { const checked = event.target.checked; setHideMaskedPrompt(checked); if (checked) setHintMode("none"); }} />Always hide the masked prompt from guessers</label>
          <CustomWordsEditor value={customWords} onChange={handleCustomWordsChange} />
          <label className="checkbox-label"><input type="checkbox" checked={customWordsOnly} disabled={wordAnalysis.usableCount === 0 || wordAnalysis.hasErrors} onChange={(event) => setCustomWordsOnly(event.target.checked)} />Only use custom words (skip the default word list)</label>
          {wordAnalysis.usableCount === 0 && <p className="setting-dependency">Add a usable custom word to enable this option.</p>}
        </div>
      </details>
      <button type="button" className="create-room-submit" disabled={busy || wordAnalysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </section>
  </main>;
}
