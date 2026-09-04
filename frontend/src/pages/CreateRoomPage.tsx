import { useEffect, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { RoomSetupForm } from "../components/RoomSetupForm";
import { SectionLabel } from "../components/ui/Card";
import { ClockIcon } from "../components/icons";
import type { PromptListSummary } from "../types";
import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "../lib/drawingRules";
import { DEFAULT_DRAWING_SECONDS, DEFAULT_HINT_MODE, hintLabelFor, scoringLabelFor } from "../lib/roomSetup";
import { createCustomPromptsState, customPromptsReducer } from "../lib/customPrompts";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import type { AckResponse, ColorMode, DrawingToolGroup, HintMode, ScoringMode } from "../types";
import { currentPlayerName, needsIdentity, useAuthStore } from "../store/authStore";
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
  // The server provisions on naming and will not open a room for a
  // visitor without an account, so the form waits rather than filling
  // itself in and failing at the last step.
  const awaitingName = needsIdentity(authUser);
  const identityResolved = useAuthStore((state) => state.hasResolved);

  // Turned away at the door rather than at the submit button: a visitor with
  // no name cannot open a room, and letting them fill in a whole form to be
  // refused at the last step is a worse answer than not opening it. The lobby
  // is where the first-run block asks for the name.
  useEffect(() => {
    if (identityResolved && awaitingName) navigate("/", { replace: true });
  }, [identityResolved, awaitingName, navigate]);
  const [roomName, setRoomName] = useState("");
  const [isPublic, setIsPublic] = useState(true);
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
  // A host who plays with colorblind-safe colors almost certainly wants the
  // room to use them too, so that is where the choice starts. It stays a
  // choice: nothing stops them picking another palette.
  const [colorMode, setColorMode] = useState<ColorMode>(
    colorblindSafeColors ? "colorblind_safe" : DEFAULT_COLOR_MODE,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The picker owns the prompt-list fetch; a copy lands here so the collapsed
  // Prompts section can summarize the selection in its header.
  const [loadedLists, setLoadedLists] = useState<PromptListSummary[]>([]);
  const [presets, setPresets] = useState<RoomPresetSummary[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetBusy, setPresetBusy] = useState(false);
  const [namingPreset, setNamingPreset] = useState(false);
  // Carries the settings that were in the form before a preset replaced them,
  // so choosing one by accident is recoverable without an Apply step.
  const [presetStatus, setPresetStatus] = useState<
    { text: string; undo?: RoomPresetSettings } | null
  >(null);

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

  /** Quick prompts and borrowed share codes are room input, never stored settings. */
  function presetBlocker(): string | null {
    if (customPrompts.analysis.usableCount > 0 || promptListShareCodes.length > 0) {
      return "Save quick prompts as a list, and remove shared codes, before storing a preset.";
    }
    return null;
  }

  function beginNamingPreset() {
    const blocked = presetBlocker();
    if (blocked) {
      setPresetStatus({ text: blocked });
      return;
    }
    setPresetName("");
    setPresetStatus(null);
    setNamingPreset(true);
  }

  function undoPreset() {
    if (presetStatus?.undo) applySettings(presetStatus.undo);
    setSelectedPresetId("");
    setPresetName("");
    setPresetStatus(null);
  }

  /** Choosing a preset applies it: the selection is the intent, so there is
      nothing left for an Apply button to confirm. Undo covers a stray click. */
  async function handleChoosePreset(id: string) {
    setSelectedPresetId(id);
    setPresetStatus(null);
    if (!id) return;
    const before = currentPresetSettings();
    setPresetBusy(true);
    setError(null);
    try {
      const preset = await getRoomPreset(id);
      applySettings(preset.settings);
      setPresetName(preset.name);
      setPresetStatus({ text: `Applied “${preset.name}”.`, undo: before });
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
      setNamingPreset(false);
      setPresetStatus({ text: `Saved “${created.name}”.` });
    } catch (presetError) {
      setError(presetError instanceof Error ? presetError.message : "Could not save that preset.");
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleUpdatePreset() {
    const selected = presets.find((preset) => preset.id === selectedPresetId);
    if (!selected) return;
    const blocked = presetBlocker();
    if (blocked) {
      setPresetStatus({ text: blocked });
      return;
    }
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
      setPresetStatus({ text: `Updated “${updated.name}”.` });
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
        nickname: currentPlayerName(), nameColor, colorblindSafeColors, name: roomName.trim(), isPublic, maxPlayers, rounds, drawingSeconds,
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

  // The form's own collapsed summaries live with the form. What is left here
  // is the one the dock carries, which is about the room as a whole.
  const selectedLists = loadedLists.filter((list) => promptListSlugs.includes(list.slug));
  const scoringSummary = `${scoringMode === "none" ? "No scoring" : `${scoringLabelFor(scoringMode)} scoring`} · ${hintLabelFor(hintMode, hideMaskedPrompt)}`;
  const footerSummary = [
    isPublic ? "Public" : "Private",
    `${maxPlayers} players`,
    `${rounds} ${rounds === 1 ? "round" : "rounds"}`,
    `${drawingSeconds}s`,
    scoringSummary,
  ].join(" · ");

  // A rough but honest running-time estimate: each turn is the drawing time
  // plus prompt choice and results, and every player draws once per round.
  const estimateMinutes = (players: number) =>
    Math.max(1, Math.round((players * rounds * (drawingSeconds + 24)) / 60));
  const fullMinutes = estimateMinutes(maxPlayers);
  const halfPlayers = Math.floor(maxPlayers / 2);
  const halfMinutes = estimateMinutes(halfPlayers);

  return <main className="create-room-page">
    <AppHeader page="Create a room" />
    <div className="create-room-heading-row">
      <div className="create-room-heading">
        <SectionLabel>Room setup</SectionLabel>
        <h1>Create a room</h1>
      </div>
      {authUser && !authUser.isAnonymous && (
        <div className="room-preset-bar">
          {presets.length > 0 && (
            <select
              aria-label="Start from a saved preset"
              value={selectedPresetId}
              disabled={presetBusy}
              onChange={(event) => void handleChoosePreset(event.target.value)}
            >
              <option value="">Start from a preset…</option>
              {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          )}
          {namingPreset ? (
            <>
              <input
                type="text"
                className="room-preset-name"
                value={presetName}
                placeholder="Name this preset"
                maxLength={64}
                autoFocus
                onChange={(event) => setPresetName(event.target.value)}
              />
              <button type="button" className="auth-link" disabled={presetBusy || !presetName.trim()} onClick={() => void handleSavePreset()}>Save</button>
              <button type="button" className="auth-link" onClick={() => setNamingPreset(false)}>Cancel</button>
            </>
          ) : (
            <>
              <button type="button" className="auth-link" disabled={presetBusy} onClick={beginNamingPreset}>Save as preset</button>
              {selectedPresetId && <button type="button" className="auth-link" disabled={presetBusy} onClick={() => void handleUpdatePreset()}>Update</button>}
              {selectedPresetId && <button type="button" className="auth-link room-preset-delete" disabled={presetBusy} onClick={() => void handleDeletePreset()}>Delete</button>}
            </>
          )}
          {presetStatus && (
            <span className="room-preset-status" role="status">
              {presetStatus.text}
              {presetStatus.undo && <button type="button" className="auth-link" onClick={undoPreset}>Undo</button>}
            </span>
          )}
        </div>
      )}
    </div>
    {error && <p className="create-room-error" role="alert">{error}</p>}

    <RoomSetupForm
      values={{
        name: roomName,
        isPublic,
        maxPlayers,
        rounds,
        drawingSeconds,
        promptListSlugs,
        promptListShareCodes,
        allowedTools,
        colorMode,
        scoringMode,
        hintMode,
        spectatorsSeePrompt,
        hideMaskedPrompt,
      }}
      onChange={(patch) => {
        if (patch.name !== undefined) setRoomName(patch.name);
        if (patch.isPublic !== undefined) setIsPublic(patch.isPublic);
        if (patch.maxPlayers !== undefined) setMaxPlayers(patch.maxPlayers);
        if (patch.rounds !== undefined) setRounds(patch.rounds);
        if (patch.drawingSeconds !== undefined) setDrawingSeconds(patch.drawingSeconds);
        if (patch.promptListSlugs !== undefined) setPromptListSlugs(patch.promptListSlugs);
        if (patch.promptListShareCodes !== undefined) setPromptListShareCodes(patch.promptListShareCodes);
        if (patch.allowedTools !== undefined) setAllowedTools(patch.allowedTools);
        if (patch.colorMode !== undefined) setColorMode(patch.colorMode);
        if (patch.scoringMode !== undefined) setScoringMode(patch.scoringMode);
        if (patch.hintMode !== undefined) setHintMode(patch.hintMode);
        if (patch.spectatorsSeePrompt !== undefined) setSpectatorsSeePrompt(patch.spectatorsSeePrompt);
        if (patch.hideMaskedPrompt !== undefined) setHideMaskedPrompt(patch.hideMaskedPrompt);
      }}
      customPrompts={customPrompts}
      dispatchCustomPrompts={dispatchCustomPrompts}
      namePlaceholder="Leave blank for a random name!"
      onListsLoaded={setLoadedLists}
      selectedLists={selectedLists}
      promptsFooter={authUser && !authUser.isAnonymous && customPrompts.analysis.usableCount > 0 && !customPrompts.analysis.hasErrors ? (
        <button
          type="button"
          className="custom-prompts-apply"
          onClick={() => navigate("/my-prompt-lists", { state: { quickPrompts: customPrompts.value } })}
        >
          Save as reusable list
        </button>
      ) : undefined}
      durationNote={
        <p className="create-room-duration">
          <ClockIcon size={17} />
          <span>
            This setup runs <strong>about {fullMinutes} minutes</strong> with a full room of{" "}
            <strong>{maxPlayers}</strong>
            {halfPlayers >= 2 && halfPlayers < maxPlayers && (
              <> — closer to <strong>{halfMinutes}</strong> if {halfPlayers} join</>
            )}
            .
          </span>
        </p>
      }
    />

    <div className="create-room-footer">
      <div className="create-room-footer-info">
        <span className="create-room-footer-summary">{footerSummary}</span>
      </div>
      <button type="button" className="btn btn-primary btn-big create-room-submit" disabled={busy || awaitingName || customPrompts.analysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </div>
  </main>;
}
