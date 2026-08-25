import { useEffect, useReducer, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CustomPromptsEditor } from "../components/CustomPromptsEditor";
import { PromptListPicker } from "../components/PromptListPicker";
import {
  ChoiceCards,
  InputNumber,
  SegmentedControl,
  Switch,
  ToggleChips,
} from "../components/RoomSetupControls";
import { AppHeader } from "../components/AppHeader";
import { SectionLabel } from "../components/ui/Card";
import {
  ChevronRightIcon,
  ClockIcon,
  GlobeIcon,
  LockIcon,
  RoundsIcon,
  UsersIcon,
} from "../components/icons";
import { promptLanguageLabel } from "../lib/promptLanguages";
import type { PromptListSummary } from "../types";
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

  // ---- collapsed-section and footer summaries -----------------------------
  const scoringLabel = SCORING_OPTIONS.find((option) => option.value === scoringMode)?.label ?? "Default";
  const hintLabel = hideMaskedPrompt
    ? "Hidden prompt"
    : HINT_OPTIONS.find((option) => option.value === hintMode)?.label ?? "Timed hints";
  const selectedLists = loadedLists.filter((list) => promptListSlugs.includes(list.slug));
  const promptsSummary = (() => {
    const parts: string[] = [];
    if (selectedLists.length > 0) {
      parts.push(promptLanguageLabel(selectedLists[0].language));
      const names = selectedLists.map((list) => list.name);
      parts.push(names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", "));
      const total = selectedLists.reduce((sum, list) => sum + list.promptCount, 0);
      if (total > 0) parts.push(`${total.toLocaleString()} prompts`);
    }
    if (customPrompts.analysis.usableCount > 0) {
      parts.push(`${customPrompts.analysis.usableCount} custom`);
    }
    return parts.join(" · ");
  })();
  const drawingSummary = [
    TOOL_GROUP_OPTIONS.filter((option) => allowedTools.includes(option.value))
      .map((option) => option.label)
      .join(", "),
    COLOR_MODE_OPTIONS.find((option) => option.value === colorMode)?.label ?? "All colors",
  ].filter(Boolean).join(" · ");
  const scoringSummary = `${scoringMode === "none" ? "No scoring" : `${scoringLabel} scoring`} · ${hintLabel}`;
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
    <AppHeader backLabel="Back to lobby" />
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

    <div className="create-room-sections">
      <section className="form-section">
        <div className="form-section-head">
          <h2>Basics</h2>
        </div>
        <div className="form-section-body">
          <div className="create-room-name-row">
            <label className="create-room-name-field">
              Room name
              {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
              <input type="search" inputMode="text" value={roomName} onChange={(event) => setRoomName(event.target.value)} maxLength={40} placeholder="Leave blank for a random name!" autoComplete="off" autoCapitalize="sentences" spellCheck={true} enterKeyHint="done" />
            </label>
            <div className="visibility-field">
              <span className="visibility-field-label" aria-hidden="true">Visibility</span>
              <SegmentedControl
                label="Visibility"
                value={isPublic ? "public" : "private"}
                onChange={(value) => setIsPublic(value === "public")}
                options={[
                  { value: "public", label: <><GlobeIcon size={14} />Public</> },
                  { value: "private", label: <><LockIcon size={14} />Private</> },
                ]}
              />
              <span className="visibility-caption">
                {isPublic
                  ? "Listed in the lobby — anyone can wander in."
                  : "Joinable only with the code or invite link."}
              </span>
            </div>
          </div>
          <div className="setting-cards">
            <InputNumber
              label="Max players"
              icon={<UsersIcon size={14} />}
              hint={`${MAX_PLAYERS_MIN}–${MAX_PLAYERS_MAX} · spectators aren't counted`}
              value={maxPlayers}
              min={MAX_PLAYERS_MIN}
              max={MAX_PLAYERS_MAX}
              onChange={setMaxPlayers}
            />
            <InputNumber
              label="Rounds"
              icon={<RoundsIcon size={14} />}
              hint={`${ROUNDS_MIN}–${ROUNDS_MAX} · everyone draws once per round`}
              value={rounds}
              min={ROUNDS_MIN}
              max={ROUNDS_MAX}
              onChange={setRounds}
            />
            <InputNumber
              label="Drawing time"
              icon={<ClockIcon size={14} />}
              unit="s"
              hint={`Snaps to presets · ${DRAWING_TIME_OPTIONS[0]}s to ${DRAWING_TIME_OPTIONS[DRAWING_TIME_OPTIONS.length - 1]}s`}
              value={drawingSeconds}
              options={DRAWING_TIME_OPTIONS}
              onChange={setDrawingSeconds}
            />
          </div>
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
        </div>
      </section>

      <details className="form-section is-collapsible">
        <summary>
          <h2>Prompts</h2>
          {promptsSummary && <span className="form-section-summary">{promptsSummary}</span>}
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <PromptListPicker
            selectedSlugs={promptListSlugs}
            onChange={setPromptListSlugs}
            shareCodes={promptListShareCodes}
            onShareCodesChange={setPromptListShareCodes}
            onListsLoaded={setLoadedLists}
          />
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

      <details className="form-section is-collapsible">
        <summary>
          <h2>Drawing</h2>
          <span className="form-section-summary">{drawingSummary}</span>
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <ToggleChips
            label="Allowed tools"
            values={allowedTools}
            onChange={setAllowedTools}
            options={TOOL_GROUP_OPTIONS.map((option) => ({
              ...option,
              disabled: !canDisallowTool(option.value, allowedTools),
            }))}
          />
          <ChoiceCards
            label="Colors"
            value={colorMode}
            onChange={setColorMode}
            columns={4}
            options={COLOR_MODE_OPTIONS}
          />
        </div>
      </details>

      <details className="form-section is-collapsible">
        <summary>
          <h2>Scoring and hints</h2>
          <span className="form-section-summary">{scoringSummary}</span>
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <ChoiceCards
            label="Scoring"
            value={scoringMode}
            columns={3}
            onChange={(mode) => {
              setScoringMode(mode);
              if (mode === "none" && (hintMode === "purchase" || hintMode === "wheel")) setHintMode("none");
            }}
            options={SCORING_OPTIONS}
          />
          <ChoiceCards
            label="Hints"
            value={hintMode}
            columns={2}
            disabled={hideMaskedPrompt}
            onChange={setHintMode}
            options={HINT_OPTIONS.map((option) => ({
              ...option,
              disabled: scoringMode === "none" && (option.value === "purchase" || option.value === "wheel"),
            }))}
          />
          {hideMaskedPrompt && <p className="setting-dependency">Hints are off because blanks are hidden.</p>}
          {hintsDisabled && !hideMaskedPrompt && <p className="setting-dependency">Point-purchase hint modes require scoring.</p>}
          <div className="form-section-switch-row">
            <Switch label="Spectators can see the prompt" checked={spectatorsSeePrompt} onChange={setSpectatorsSeePrompt} />
            <Switch
              label="Hide blanks"
              hint="Also turns hints off: with no blanks there is nothing to reveal."
              checked={hideMaskedPrompt}
              onChange={(checked) => {
                setHideMaskedPrompt(checked);
                if (checked) setHintMode("none");
              }}
            />
          </div>
        </div>
      </details>
    </div>

    <div className="create-room-footer">
      <div className="create-room-footer-info">
        <span className="create-room-footer-summary">{footerSummary}</span>
        <Switch
          label="Keep this room for future games"
          hint={authUser && !authUser.isAnonymous
            ? "The code and settings stay with your account. Quick custom prompts must be saved as a prompt list first."
            : "Create an account to own a persistent room."}
          checked={persistent}
          disabled={!authUser || authUser.isAnonymous || customPrompts.analysis.usableCount > 0}
          onChange={setPersistent}
        />
      </div>
      <button type="button" className="btn btn-primary btn-big create-room-submit" disabled={busy || customPrompts.analysis.hasErrors} onClick={() => void handleCreate()}>{busy ? "Creating…" : "Create room"}</button>
    </div>
  </main>;
}
