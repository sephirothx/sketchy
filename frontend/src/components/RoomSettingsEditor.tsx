import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { RoomSetupForm, type RoomSetupValues } from "./RoomSetupForm";
import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "../lib/drawingRules";
import { DEFAULT_DRAWING_SECONDS, DEFAULT_HINT_MODE } from "../lib/roomSetup";
import { createCustomPromptsState, customPromptsReducer } from "../lib/customPrompts";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useToast } from "../lib/toast";
import { useGameStore } from "../store/gameStore";
import type { AckResponse, EditableRoomSettings, PromptListSummary } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

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
  promptListShareCodes: [],
};

function toFormValues(settings: EditableRoomSettings): RoomSetupValues {
  return {
    name: settings.name,
    isPublic: settings.isPublic,
    maxPlayers: settings.maxPlayers,
    rounds: settings.rounds,
    drawingSeconds: settings.drawingSeconds,
    promptLanguage: settings.promptLanguage,
    promptListSlugs: settings.promptListSlugs || ["english_standard"],
    promptListShareCodes: settings.promptListShareCodes || [],
    allowedTools: settings.allowedTools,
    colorMode: settings.colorMode,
    scoringMode: settings.scoringMode,
    hintMode: settings.hintMode,
    spectatorsSeePrompt: settings.spectatorsSeePrompt,
    hideMaskedPrompt: settings.hideMaskedPrompt,
  };
}

interface RoomSettingsEditorProps {
  /** Called after the room has accepted the whole draft. */
  onSaved?: () => void;
  onCancel?: () => void;
}

/**
 * The host's editor for a room that is waiting.
 *
 * The same form as `/create`, and the same save shape as `/create`: a draft
 * that is nobody's business until it is submitted. It used to save every field
 * as it was touched, which was the right answer when settings were a panel
 * permanently open beside the room — a host nudging a stepper wanted the room
 * to follow. Behind a dialog it is the wrong one: a half-made decision is not
 * a decision, and every intermediate value on the way to "6 rounds" was being
 * broadcast to everyone waiting.
 */
export function RoomSettingsEditor({ onSaved, onCancel }: RoomSettingsEditorProps = {}) {
  const [values, setValues] = useState<RoomSetupValues>(toFormValues(emptySettings));
  const [baseline, setBaseline] = useState<RoomSetupValues>(toFormValues(emptySettings));
  const [loadedLists, setLoadedLists] = useState<PromptListSummary[]>([]);
  // The colors are the one setting the room can change without this form
  // asking: accepting the colorblind-safe suggestion switches the palette
  // server-side. A draft the host has not saved is theirs, so the room's
  // change only moves the baseline — what "unchanged" means — and the field
  // itself follows only while the host has not touched it.
  const roomColorMode = useGameStore((state) => state.colorMode);
  const [seenColorMode, setSeenColorMode] = useState(roomColorMode);
  if (roomColorMode !== seenColorMode) {
    setSeenColorMode(roomColorMode);
    setValues((current) =>
      current.colorMode === baseline.colorMode && current.colorMode !== roomColorMode
        ? { ...current, colorMode: roomColorMode }
        : current,
    );
    setBaseline((current) => ({ ...current, colorMode: roomColorMode }));
  }

  const [customPrompts, dispatchCustomPrompts] = useReducer(
    customPromptsReducer,
    undefined,
    () => createCustomPromptsState(),
  );
  const [promptsBaseline, setPromptsBaseline] = useState({ value: "", only: false });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { notify } = useToast();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await emitWithAck<{ ok: boolean; error?: string; settings?: EditableRoomSettings }>("get_room_settings", {});
        if (cancelled) return;
        if (response.ok && response.settings) {
          const loaded = toFormValues(response.settings);
          setValues(loaded);
          setBaseline(loaded);
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
        else setError(refusalText(response, ui.roomSettingsEditor.couldNotLoadRoomRules));
      } catch (loadError) {
        if (!cancelled) setError(socketRequestErrorMessage(loadError, ui.roomSettingsEditor.loadRoomRules));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const promptsError = customPrompts.analysis.hasErrors;
  const dirty = useMemo(() => {
    const changed = (Object.keys(values) as (keyof RoomSetupValues)[]).some((key) => {
      const next = values[key];
      const previous = baseline[key];
      return Array.isArray(next) && Array.isArray(previous)
        ? next.length !== previous.length || next.some((item, index) => item !== previous[index])
        : next !== previous;
    });
    return changed
      || customPrompts.value !== promptsBaseline.value
      || customPrompts.only !== promptsBaseline.only;
  }, [values, baseline, customPrompts.value, customPrompts.only, promptsBaseline]);

  const handleChange = useCallback((patch: Partial<RoomSetupValues>) => {
    setValues((current) => ({ ...current, ...patch }));
  }, []);

  async function save() {
    if (saving || promptsError) return;
    setSaving(true);
    setError(null);
    try {
      // The room's language is fixed at creation (R-PROMPT-02), so it is not
      // in the update at all: the server refuses the key outright rather than
      // comparing it with what the room already holds.
      const editable: Partial<RoomSetupValues> = { ...values };
      delete editable.promptLanguage;
      const response = await emitWithAck<AckResponse>("update_room_settings", {
        ...editable,
        customPrompts: customPrompts.value,
        customPromptsOnly: customPrompts.only,
      });
      if (response?.ok === false) {
        // The server settles dependent settings itself — a hint mode the
        // scoring rules out, say — so a refusal is not simply "put the old
        // value back"; the form reloads from what the room actually holds.
        const message = refusalText(response, ui.roomSettingsEditor.roomRefusedThoseSettings);
        setError(message);
        notify(message, "error");
        return;
      }
      setBaseline(values);
      setPromptsBaseline({ value: customPrompts.value, only: customPrompts.only });
      onSaved?.();
    } catch (saveError) {
      const message = socketRequestErrorMessage(saveError, ui.roomSettingsEditor.saveRoomRules);
      setError(message);
      notify(message, "error");
    } finally {
      setSaving(false);
    }
  }

  // No card of its own: the dialog it opens in is already a panel, and two
  // nested ones cost 90px of a phone's width in padding and borders alone.
  return <section
    className="room-settings-editor"
    aria-labelledby="room-settings-title"
  >
    <div className="room-settings-editor-heading">
      <p className="waiting-card-kicker">{ui.roomSettingsEditor.hostSettings}</p>
      <h2 id="room-settings-title">{ui.roomSettingsEditor.editRoomRules}</h2>
    </div>
    {loading ? <p>{ui.roomSettingsEditor.loadingSettings}</p> : (
      <RoomSetupForm
        values={values}
        onChange={handleChange}
        customPrompts={customPrompts}
        dispatchCustomPrompts={dispatchCustomPrompts}
        onListsLoaded={setLoadedLists}
        loadedLists={loadedLists}
        languageLocked
      />
    )}
    {error && <p className="create-room-error" role="alert">{error}</p>}
    <div className="room-settings-actions">
      {onCancel && (
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          {ui.roomSettingsEditor.cancel}
        </button>
      )}
      <button
        type="button"
        className="btn btn-primary room-settings-save"
        disabled={!dirty || saving || promptsError || loading}
        onClick={() => void save()}
      >
        {saving ? ui.roomSettingsEditor.saving : dirty ? ui.roomSettingsEditor.saveSettings : ui.roomSettingsEditor.saved}
      </button>
    </div>
  </section>;
}
