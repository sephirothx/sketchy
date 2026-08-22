import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { CustomPromptsEditor } from "./CustomPromptsEditor";
import { PromptListPicker } from "./PromptListPicker";
import {
  ChoiceChips,
  InputNumber,
  SegmentedControl,
  Switch,
  ToggleChips,
} from "./RoomSetupControls";
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
import type {
  AckResponse,
  ColorMode,
  DrawingToolGroup,
  EditableRoomSettings,
  HintMode,
  ScoringMode,
} from "../types";

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
  allowedTools: DEFAULT_ALLOWED_TOOLS,
  colorMode: DEFAULT_COLOR_MODE,
  promptLanguage: "en",
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
  // server clears "only" whenever the prompt list it is given is empty.
  //
  // This is what has been handed over, set the moment a patch is queued rather
  // than when it comes back. Waiting for the acknowledgement would leave the
  // block dirty for a whole round-trip, and clicking Apply blurs the textarea
  // on the way - so the blur and the click would each send the same prompts.
  const [promptsBaseline, setPromptsBaseline] = useState({ value: "", only: false });
  // Re-read the room's settings. Bumped after a refusal, which is the one time
  // the form and the room can disagree about what a setting is. Re-reading
  // rather than putting back a locally remembered value: the server settles
  // dependent settings itself - a hint mode the scoring rules out, say - so
  // what it holds is not always what this form last sent it.
  const [reloadCount, setReloadCount] = useState(0);
  const rootRef = useRef<HTMLElement>(null);
  const { notify } = useToast();

  const promptsDirty =
    customPrompts.value !== promptsBaseline.value
    || customPrompts.only !== promptsBaseline.only;

  const saver = useMemo(() => createRoomSettingsSaver({
    send: (patch) => emitWithAck<AckResponse>("update_room_settings", patch),
    onStatus: setStatus,
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
          // The baseline always takes what the room actually holds, which is
          // what corrects the guess made when the prompts were handed over: a
          // patch they were merged into can be refused for something else
          // entirely, and the block has to go back to offering Apply.
          setPromptsBaseline({
            value: response.settings.customPrompts,
            only: response.settings.customPromptsOnly,
          });
          // The text itself is only filled in on the first read. A re-read
          // follows a refusal, which says nothing about a prompt list the host
          // is still writing - and that draft has never been anywhere it could
          // be recovered from.
          if (reloadCount === 0) {
            dispatchCustomPrompts({
              type: "reset",
              value: response.settings.customPrompts,
              only: response.settings.customPromptsOnly,
            });
          }
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
    // Reaching for anything outside this panel - Start game, above all - ends
    // the host's business with it, so whatever is still waiting out its delay
    // goes now. Watching the press rather than the click is what makes this
    // work: the settings are on the socket before the start is, and the socket
    // delivers in order. A press and not only a blur, because a button does
    // not take focus on every browser.
    const flushOnPressOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) saver.flush();
    };
    document.addEventListener("pointerdown", flushOnPressOutside, true);
    return () => {
      socket.off("connect", retry);
      document.removeEventListener("pointerdown", flushOnPressOutside, true);
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
    setPromptsBaseline({ value: customPrompts.value, only: customPrompts.only });
    saver.queue({ customPrompts: customPrompts.value, customPromptsOnly: customPrompts.only });
    saver.flush();
  }, [customPrompts.only, customPrompts.value, promptsDirty, promptsError, saver]);

  // The switch always carries the textarea's current contents with it. Sent
  // alone it would have the server judge "only" against the prompt list it
  // already has - and the host reaching for the switch has, by definition,
  // finished with the textarea.
  function setPromptsOnly(only: boolean) {
    dispatchCustomPrompts({ type: "set-only", only });
    setPromptsBaseline({ value: customPrompts.value, only });
    saver.queue({ customPrompts: customPrompts.value, customPromptsOnly: only });
    saver.flush();
  }

  function updateNumber(field: "maxPlayers" | "rounds" | "drawingSeconds", value: number) {
    setSettings((current) => ({ ...current, [field]: value }));
    if (isSendableRoomNumber(field, value)) saver.queue({ [field]: value }, STEPPER_SAVE_DELAY_MS);
  }

  return <section
    ref={rootRef}
    className="waiting-card room-settings-editor"
    aria-labelledby="room-settings-title"
    // Focus leaving a field is the keyboard's version of the press above: it
    // is how a host tabbing to Start game gets there without outrunning their
    // own edit.
    onBlur={() => saver.flush()}
  >
    <div className="room-settings-editor-heading"><p className="waiting-card-kicker">Host settings</p><h2 id="room-settings-title">Edit room settings</h2></div>
    {loading ? <p>Loading settings…</p> : <div className="room-settings-fields">
      <div className="create-room-name-row">
        <label className="create-room-name-field">
          Room name
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar. */}
          <input type="search" inputMode="text" value={settings.name} onChange={(event) => update({ name: event.target.value }, TYPING_SAVE_DELAY_MS)} maxLength={40} autoComplete="off" autoCapitalize="sentences" spellCheck={true} enterKeyHint="done" />
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
      <ToggleChips
        label="Allowed tools"
        values={settings.allowedTools}
        onChange={(allowedTools: DrawingToolGroup[]) => update({ allowedTools })}
        options={TOOL_GROUP_OPTIONS.map((option) => ({
          ...option,
          disabled: !canDisallowTool(option.value, settings.allowedTools),
        }))}
      />
      <ChoiceChips
        label="Colors"
        value={settings.colorMode}
        onChange={(colorMode: ColorMode) => update({ colorMode })}
        options={COLOR_MODE_OPTIONS}
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
