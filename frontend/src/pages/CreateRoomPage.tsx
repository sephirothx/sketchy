import { useEffect, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/AppHeader";
import { RoomSetupForm } from "../components/RoomSetupForm";
import { SectionLabel } from "../components/ui/Card";
import { ClockIcon } from "../components/icons";
import type { PromptListSummary } from "../types";
import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "../lib/drawingRules";
import { DEFAULT_DRAWING_SECONDS, DEFAULT_HINT_MODE, hintLabelFor, scoringNameFor } from "../lib/roomSetup";
import { createCustomPromptsState, customPromptsReducer } from "../lib/customPrompts";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { sessionFrom } from "../lib/roomEntryState";
import { useGameStore } from "../store/gameStore";
import { useSettingsStore } from "../store/settingsStore";
import { reconcileSelectionForLanguage } from "../lib/promptLanguages";
import type { AckResponse, ColorMode, DrawingToolGroup, HintMode, PromptLanguage, ScoringMode } from "../types";
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
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";

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
  // The language this player plays in - their setting if they have an account,
  // and what their browser says otherwise. A host who wants another one says
  // so in the form; this is only where it starts.
  const [promptLanguage, setPromptLanguage] = useState<PromptLanguage>(
    () => useSettingsStore.getState().promptLanguage,
  );
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
        if (!cancelled) setError(ui.createRoomPage.couldNotLoadYourRoomPresets);
      });
    return () => { cancelled = true; };
  }, [authUser]);

  /**
   * The catalogue arriving is when the guess above becomes checkable.
   *
   * The language comes from the player's own preference and the selection
   * from a constant, and nothing kept the two in step: someone who plays in
   * German opened this form declaring German with `english_standard`
   * selected, which the server refuses. The lists say which slugs belong to
   * the language, so this is the first moment the selection can be put right.
   */
  function handleListsLoaded(lists: PromptListSummary[]) {
    setLoadedLists(lists);
    setPromptListSlugs((current) =>
      reconcileSelectionForLanguage(lists, promptLanguage, current),
    );
  }

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
      promptLanguage,
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
    // A preset carries the language of the lists it saved, and applying it
    // sets both together: a room declares its language before it has lists.
    setPromptLanguage(settings.promptLanguage);
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
      return ui.createRoomPage.saveQuickPromptsAsA;
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
      setPresetStatus({ text: ui.createRoomPage.appliedName({ name: preset.name }), undo: before });
    } catch (presetError) {
      setError(refusalText(presetError, ui.createRoomPage.couldNotApplyThatPreset));
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleSavePreset() {
    if (!presetName.trim()) {
      setError(ui.createRoomPage.enterNameRoomPreset);
      return;
    }
    setPresetBusy(true);
    setError(null);
    try {
      const created = await createRoomPreset(presetName, currentPresetSettings());
      await refreshPresets(created.id);
      setPresetName(created.name);
      setNamingPreset(false);
      setPresetStatus({ text: ui.createRoomPage.savedName({ name: created.name }) });
    } catch (presetError) {
      setError(refusalText(presetError, ui.createRoomPage.couldNotSaveThatPreset));
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
      setPresetStatus({ text: ui.createRoomPage.updatedName({ name: updated.name }) });
      setPresetName(updated.name);
    } catch (presetError) {
      setError(refusalText(presetError, ui.createRoomPage.couldNotUpdateThatPreset));
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleDeletePreset() {
    if (!selectedPresetId) return;
    if (!window.confirm(ui.createRoomPage.deleteThisRoomSettingPreset)) return;
    setPresetBusy(true);
    setError(null);
    try {
      await deleteRoomPreset(selectedPresetId);
      await refreshPresets("");
      setSelectedPresetId("");
      setPresetName("");
    } catch (presetError) {
      setError(refusalText(presetError, ui.createRoomPage.couldNotDeleteThatPreset));
    } finally {
      setPresetBusy(false);
    }
  }

  async function handleCreate() {
    if (customPrompts.analysis.hasErrors) {
      setError(ui.createRoomPage.fixCustomPromptEntriesMarkedAbove);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("create_room", {
        nickname: currentPlayerName(), nameColor, colorblindSafeColors, name: roomName.trim(), isPublic, maxPlayers, rounds, drawingSeconds,
        customPrompts: customPrompts.value.trim(), customPromptsOnly: customPrompts.only, hintMode, scoringMode,
        spectatorsSeePrompt, hideMaskedPrompt, allowedTools, colorMode, promptLanguage,
        promptListSlugs, promptListShareCodes,
      });
      const session = sessionFrom(response);
      if (session) {
        setSession(session);
        navigate(`/room/${session.code}`);
        return;
      }
      setError(refusalText(response, ui.createRoomPage.failedCreateRoom));
    } catch (createError) {
      setError(socketRequestErrorMessage(createError, ui.createRoomPage.createTheRoom));
    } finally {
      setBusy(false);
    }
  }

  // The form's own collapsed summaries live with the form. What is left here
  // is the one the dock carries, which is about the room as a whole.
  const scoringSummary = `${scoringMode === "none" ? ui.createRoomPage.noScoring : scoringNameFor(scoringMode)} · ${hintLabelFor(hintMode, hideMaskedPrompt)}`;
  const footerSummary = [
    isPublic ? ui.createRoomPage.public : ui.createRoomPage.private,
    ui.createRoomPage.playerCount({ count: maxPlayers }),
    ui.createRoomPage.roundCount({ count: rounds }),
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
    <AppHeader backLabel={ui.createRoomPage.backToLobby} />
    <div className="create-room-heading-row">
      <div className="create-room-heading">
        <SectionLabel>{ui.createRoomPage.roomSetup}</SectionLabel>
        <h1>{ui.createRoomPage.createRoom}</h1>
      </div>
      {authUser && !authUser.isAnonymous && (
        <div className="room-preset-bar">
          {presets.length > 0 && (
            <select
              aria-label={ui.createRoomPage.startFromSavedPreset}
              value={selectedPresetId}
              disabled={presetBusy}
              onChange={(event) => void handleChoosePreset(event.target.value)}
            >
              <option value="">{ui.createRoomPage.startFromPreset}</option>
              {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          )}
          {namingPreset ? (
            <>
              <input
                type="text"
                className="room-preset-name"
                value={presetName}
                placeholder={ui.createRoomPage.nameThisPreset}
                maxLength={64}
                autoFocus
                onChange={(event) => setPresetName(event.target.value)}
              />
              <button type="button" className="auth-link" disabled={presetBusy || !presetName.trim()} onClick={() => void handleSavePreset()}>{ui.createRoomPage.save}</button>
              <button type="button" className="auth-link" onClick={() => setNamingPreset(false)}>{ui.createRoomPage.cancel}</button>
            </>
          ) : (
            <>
              <button type="button" className="auth-link" disabled={presetBusy} onClick={beginNamingPreset}>{ui.createRoomPage.saveAsPreset}</button>
              {selectedPresetId && <button type="button" className="auth-link" disabled={presetBusy} onClick={() => void handleUpdatePreset()}>{ui.createRoomPage.update}</button>}
              {selectedPresetId && <button type="button" className="auth-link room-preset-delete" disabled={presetBusy} onClick={() => void handleDeletePreset()}>{ui.createRoomPage.delete}</button>}
            </>
          )}
          {presetStatus && (
            <span className="room-preset-status" role="status">
              {presetStatus.text}
              {presetStatus.undo && <button type="button" className="auth-link" onClick={undoPreset}>{ui.createRoomPage.undo}</button>}
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
        promptLanguage,
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
        if (patch.promptLanguage !== undefined) setPromptLanguage(patch.promptLanguage);
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
      namePlaceholder={ui.createRoomPage.leaveBlankForARandom}
      onListsLoaded={handleListsLoaded}
      loadedLists={loadedLists}
      promptsFooter={authUser && !authUser.isAnonymous && customPrompts.analysis.usableCount > 0 && !customPrompts.analysis.hasErrors ? (
        <button
          type="button"
          className="custom-prompts-apply"
          onClick={() => navigate("/my-prompt-lists", { state: { quickPrompts: customPrompts.value } })}
        >
          {ui.createRoomPage.saveAsReusableList}
        </button>
      ) : undefined}
      durationNote={
        <p className="create-room-duration">
          <ClockIcon size={17} />
          <span>
            {fill(ui.createRoomPage.setupTiming, {
              full: (
                <strong>
                  {ui.createRoomPage.setupTimingFull({ minutes: fullMinutes })}
                </strong>
              ),
              capacity: <strong>{maxPlayers}</strong>,
            })}
            {halfPlayers >= 2 && halfPlayers < maxPlayers
              && fill(
                ui.createRoomPage.setupTimingHalf({ players: halfPlayers }),
                { half: <strong>{halfMinutes}</strong> },
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
      <button type="button" className="btn btn-primary btn-big create-room-submit" disabled={busy || awaitingName || customPrompts.analysis.hasErrors} onClick={() => void handleCreate()}>{busy ? ui.createRoomPage.creating : ui.createRoomPage.createRoom2}</button>
    </div>
  </main>;
}
