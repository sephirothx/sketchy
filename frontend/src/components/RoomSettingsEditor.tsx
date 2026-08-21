import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
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
  isSendableRoomNumber,
} from "../lib/roomSetup";
import { createCustomPromptsState, customPromptsReducer } from "../lib/customPrompts";
import {
  STEPPER_SAVE_DELAY_MS,
  TYPING_SAVE_DELAY_MS,
  createRoomSettingsSaver,
  type RoomSettingsPatch,
  type SaveStatus,
} from "../lib/roomSettingsAutosave";
import { emitWithAck, socket, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
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
  spectatorsSeePrompt: false,
  hideMaskedPrompt: false,
  promptListSlugs: ["english_standard"],
};

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: "",
  pending: "",
  saving: "Saving…",
  saved: "Saved",
  failed: "Not saved — retrying",
};

export function RoomSettingsEditor() {
  const [settings, setSettings] = useState<EditableRoomSettings>(emptySettings);
  const [customPrompts, dispatchCustomPrompts] = useReducer(
    customPromptsReducer,
    undefined,
    () => createCustomPromptsState(),
  );
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  // Custom prompts do not autosave: a prompt list only means anything once the
  // host has stopped typing it, and a half-written line would be stored as a
  // prompt. The textarea and the "only" switch travel together, because the
  // server clears "only" whenever the prompt list it is given is empty. This
  // is what the server last accepted, so the Apply button knows it has work.
  const [promptsBaseline, setPromptsBaseline] = useState({ value: "", only: false });
  // Re-read the room's settings. Bumped after a refusal, which is the one time
  // the form and the room can disagree about what a setting is.
  const [reloadCount, setReloadCount] = useState(0);
  const { notify } = useToast();

  const promptsDirty =
    customPrompts.value !== promptsBaseline.value
    || customPrompts.only !== promptsBaseline.only;

  const saver = useMemo(() => createRoomSettingsSaver({
    send: (patch) => emitWithAck<AckResponse>("update_room_settings", patch),
    onStatus: setStatus,
    onConfirmed: (patch) => setPromptsBaseline((baseline) => (
      patch.customPrompts === undefined && patch.customPromptsOnly === undefined
        ? baseline
        : {
          value: patch.customPrompts ?? baseline.value,
          only: patch.customPromptsOnly ?? baseline.only,
        }
    )),
    onRejected: (message) => {
      notify(message, "error");
      setReloadCount((count) => count + 1);
    },
  }), [notify]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await emitWithAck<{ ok: boolean; error?: string; settings?: EditableRoomSettings }>("get_room_settings", {});
        if (cancelled) return;
        if (response.ok && response.settings) {
          setSettings(response.settings);
          setPromptsBaseline({
            value: response.settings.customPrompts,
            only: response.settings.customPromptsOnly,
          });
          dispatchCustomPrompts({
            type: "reset",
            value: response.settings.customPrompts,
            only: response.settings.customPromptsOnly,
          });
          setError(null);
        }
        else setError(response.error || "Could not load room settings");
      } catch (loadError) {
        if (!cancelled) setError(socketRequestErrorMessage(loadError, "load room settings"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [reloadCount]);

  useEffect(() => {
    // A patch held back by a dropped connection goes out as soon as there is
    // one again, so the host's last change survives the reconnect.
    const retry = () => saver.flush();
    socket.on("connect", retry);
    return () => {
      socket.off("connect", retry);
      // A change the host made a moment before leaving the lobby still goes
      // out - forgetting it here is the very thing this editor stopped doing.
      saver.flush();
      saver.reset();
    };
  }, [saver]);

  const update = useCallback((patch: RoomSettingsPatch, delayMs?: number) => {
    setSettings((current) => ({ ...current, ...patch }));
    saver.queue(patch, delayMs);
  }, [saver]);

  // Shown locally rather than as a toast: it is a property of what is in the
  // textarea, and it has to stay visible while the host fixes it.
  const promptsError = customPrompts.analysis.hasErrors;

  const applyPrompts = useCallback(() => {
    if (promptsError || !promptsDirty) return;
    saver.queue({ customPrompts: customPrompts.value, customPromptsOnly: customPrompts.only });
    saver.flush();
  }, [customPrompts.only, customPrompts.value, promptsDirty, promptsError, saver]);

  // The switch always carries the textarea's current contents with it. Sent
  // alone it would have the server judge "only" against the prompt list it
  // already has - and the host reaching for the switch has, by definition,
  // finished with the textarea.
  function setPromptsOnly(only: boolean) {
    dispatchCustomPrompts({ type: "set-only", only });
    saver.queue({ customPrompts: customPrompts.value, customPromptsOnly: only });
    saver.flush();
  }

  function updateNumber(field: "maxPlayers" | "rounds" | "drawingSeconds", value: number) {
    setSettings((current) => ({ ...current, [field]: value }));
    if (isSendableRoomNumber(field, value)) saver.queue({ [field]: value }, STEPPER_SAVE_DELAY_MS);
  }

  return <section className="waiting-card room-settings-editor" aria-labelledby="room-settings-title">
    <div className="room-settings-editor-heading"><p className="waiting-card-kicker">Host settings</p><h2 id="room-settings-title">Edit room settings</h2></div>
    {loading ? <p>Loading settings…</p> : <div className="room-settings-fields">
      <div className="create-room-name-row">
        <label className="create-room-name-field">
          Room name
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
          <input type="search" inputMode="text" value={settings.name} onChange={(event) => update({ name: event.target.value }, TYPING_SAVE_DELAY_MS)} onBlur={() => saver.flush()} maxLength={40} autoComplete="off" autoCapitalize="sentences" spellCheck={true} enterKeyHint="done" />
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
      <InputNumber label="Max players" value={settings.maxPlayers} min={MAX_PLAYERS_MIN} max={MAX_PLAYERS_MAX} onChange={(maxPlayers) => updateNumber("maxPlayers", maxPlayers)} />
      <InputNumber label="Rounds" value={settings.rounds} min={ROUNDS_MIN} max={ROUNDS_MAX} onChange={(rounds) => updateNumber("rounds", rounds)} />
      <InputNumber label="Drawing time (seconds)" value={settings.drawingSeconds} options={DRAWING_TIME_OPTIONS} onChange={(drawingSeconds) => updateNumber("drawingSeconds", drawingSeconds)} />
      <PromptListPicker
        selectedSlugs={settings.promptListSlugs || ["english_standard"]}
        onChange={(promptListSlugs) => update({ promptListSlugs })}
      />
      <details><summary>Advanced settings</summary><div className="room-settings-advanced">
        <Switch label="Allow spectators to see the prompt" checked={settings.spectatorsSeePrompt} onChange={(spectatorsSeePrompt) => update({ spectatorsSeePrompt })} />
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
        <CustomPromptsEditor
          value={customPrompts.value}
          analysis={customPrompts.analysis}
          onChange={(value) => dispatchCustomPrompts({ type: "change", value })}
          onCommit={applyPrompts}
          footer={
            <button
              type="button"
              className="custom-prompts-apply"
              disabled={!promptsDirty || promptsError}
              onClick={applyPrompts}
            >
              {promptsDirty ? "Apply prompts" : "Prompts applied"}
            </button>
          }
        />
        <Switch
          label="Only use custom prompts"
          hint="Add a usable custom prompt to enable this option."
          checked={customPrompts.only}
          disabled={customPrompts.analysis.usableCount === 0 || promptsError}
          onChange={setPromptsOnly}
        />
      </div></details>
    </div>}
    {error && <p className="create-room-error" role="alert">{error}</p>}
    <div className={`room-settings-status${status === "failed" ? " is-failed" : ""}`} aria-live="polite">
      {STATUS_TEXT[status]}
    </div>
  </section>;
}
