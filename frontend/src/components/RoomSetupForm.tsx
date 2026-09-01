import type { ReactNode } from "react";
import { CustomPromptsEditor } from "./CustomPromptsEditor";
import { PromptListPicker } from "./PromptListPicker";
import {
  ChoiceCards,
  InputNumber,
  SegmentedControl,
  Switch,
  ToggleChips,
} from "./RoomSetupControls";
import {
  ChevronRightIcon,
  ClockIcon,
  GlobeIcon,
  LockIcon,
  RoundsIcon,
  UsersIcon,
} from "./icons";
import {
  COLOR_MODE_OPTIONS,
  TOOL_GROUP_OPTIONS,
  canDisallowTool,
} from "../lib/drawingRules";
import {
  DRAWING_TIME_OPTIONS,
  HINT_OPTIONS,
  MAX_PLAYERS_MAX,
  MAX_PLAYERS_MIN,
  ROUNDS_MAX,
  ROUNDS_MIN,
  SCORING_OPTIONS,
  hintLabelFor,
  scoringLabelFor,
} from "../lib/roomSetup";
import { promptLanguageLabel } from "../lib/promptLanguages";
import type { CustomPromptsAction, CustomPromptsState } from "../lib/customPrompts";
import type {
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PromptListSummary,
  ScoringMode,
} from "../types";

/** Everything both surfaces set. Custom prompts travel beside it, because they
    are a reducer rather than a value. */
export interface RoomSetupValues {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  promptListSlugs: string[];
  promptListShareCodes: string[];
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  scoringMode: ScoringMode;
  hintMode: HintMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
}

interface RoomSetupFormProps {
  values: RoomSetupValues;
  onChange: (patch: Partial<RoomSetupValues>) => void;
  customPrompts: CustomPromptsState;
  dispatchCustomPrompts: (action: CustomPromptsAction) => void;
  /** Create shows a "leave blank" placeholder; a room already has a name. */
  namePlaceholder?: string;
  /** Create offers "Save as reusable list" under the prompt box. */
  promptsFooter?: ReactNode;
  onListsLoaded?: (lists: PromptListSummary[]) => void;
  /** Create puts its running-time estimate under the three numbers. */
  durationNote?: ReactNode;
  selectedLists?: PromptListSummary[];
}

/**
 * The room-setup form, shared by `/create` and the host's editor in the
 * waiting room.
 *
 * One component rather than two arrangements of the same controls: the editor
 * used to be a flat column of fields where creation was four labelled
 * sections, so the same room could be described two different ways depending
 * on which screen you were on. Everything that differs between the two — the
 * presets bar, the name placeholder, the duration estimate, whether changes
 * save as you go or on a button — stays outside this component.
 */
export function RoomSetupForm({
  values,
  onChange,
  customPrompts,
  dispatchCustomPrompts,
  namePlaceholder,
  promptsFooter,
  onListsLoaded,
  durationNote,
  selectedLists = [],
}: RoomSetupFormProps) {
  const {
    name,
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
  } = values;

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

  const scoringSummary = `${scoringMode === "none" ? "No scoring" : `${scoringLabelFor(scoringMode)} scoring`} · ${hintLabelFor(hintMode, hideMaskedPrompt)}`;
  const hintsDisabled = hideMaskedPrompt || scoringMode === "none";

  return (
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
              <input
                type="search"
                inputMode="text"
                value={name}
                onChange={(event) => onChange({ name: event.target.value })}
                maxLength={40}
                placeholder={namePlaceholder}
                autoComplete="off"
                autoCapitalize="sentences"
                spellCheck={true}
                enterKeyHint="done"
              />
            </label>
            <div className="visibility-field">
              <span className="visibility-field-label" aria-hidden="true">Visibility</span>
              <SegmentedControl
                label="Visibility"
                value={isPublic ? "public" : "private"}
                onChange={(value) => onChange({ isPublic: value === "public" })}
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
            {/* No hints under these three. The ranges are enforced by the
                controls themselves, "everyone draws once per round" is what a
                round is, and the line below already says what the three of
                them add up to in minutes. */}
            <InputNumber
              label="Max players"
              icon={<UsersIcon size={14} />}
              value={maxPlayers}
              min={MAX_PLAYERS_MIN}
              max={MAX_PLAYERS_MAX}
              onChange={(value) => onChange({ maxPlayers: value })}
            />
            <InputNumber
              label="Rounds"
              icon={<RoundsIcon size={14} />}
              value={rounds}
              min={ROUNDS_MIN}
              max={ROUNDS_MAX}
              onChange={(value) => onChange({ rounds: value })}
            />
            <InputNumber
              label="Drawing time"
              icon={<ClockIcon size={14} />}
              unit="s"
              value={drawingSeconds}
              options={DRAWING_TIME_OPTIONS}
              onChange={(value) => onChange({ drawingSeconds: value })}
            />
          </div>
          {durationNote}
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
            onChange={(slugs) => onChange({ promptListSlugs: slugs })}
            shareCodes={promptListShareCodes}
            onShareCodesChange={(codes) => onChange({ promptListShareCodes: codes })}
            onListsLoaded={onListsLoaded}
          />
          <CustomPromptsEditor
            value={customPrompts.value}
            analysis={customPrompts.analysis}
            onChange={(value) => dispatchCustomPrompts({ type: "change", value })}
            footer={promptsFooter}
          />
          <Switch
            label="Only use custom prompts"
            hint="Add a usable custom prompt to enable this option."
            checked={customPrompts.only}
            disabled={customPrompts.analysis.usableCount === 0 || customPrompts.analysis.hasErrors}
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
            onChange={(tools: DrawingToolGroup[]) => onChange({ allowedTools: tools })}
            options={TOOL_GROUP_OPTIONS.map((option) => ({
              ...option,
              disabled: !canDisallowTool(option.value, allowedTools),
            }))}
          />
          <ChoiceCards
            label="Colors"
            value={colorMode}
            onChange={(mode: ColorMode) => onChange({ colorMode: mode })}
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
            onChange={(mode: ScoringMode) => onChange({
              scoringMode: mode,
              hintMode: mode === "none" && (hintMode === "purchase" || hintMode === "wheel")
                ? "none"
                : hintMode,
            })}
            options={SCORING_OPTIONS}
          />
          <ChoiceCards
            label="Hints"
            value={hintMode}
            columns={2}
            disabled={hideMaskedPrompt}
            onChange={(mode: HintMode) => onChange({ hintMode: mode })}
            options={HINT_OPTIONS.map((option) => ({
              ...option,
              disabled: scoringMode === "none" && (option.value === "purchase" || option.value === "wheel"),
            }))}
          />
          {hideMaskedPrompt && <p className="setting-dependency">Hints are off because blanks are hidden.</p>}
          {hintsDisabled && !hideMaskedPrompt && <p className="setting-dependency">Point-purchase hint modes require scoring.</p>}
          <div className="form-section-switch-row">
            <Switch
              label="Spectators can see the prompt"
              checked={spectatorsSeePrompt}
              onChange={(checked) => onChange({ spectatorsSeePrompt: checked })}
            />
            <Switch
              label="Hide blanks"
              hint="Also turns hints off: with no blanks there is nothing to reveal."
              checked={hideMaskedPrompt}
              onChange={(checked) => onChange({
                hideMaskedPrompt: checked,
                hintMode: checked ? "none" : hintMode,
              })}
            />
          </div>
        </div>
      </details>
    </div>
  );
}
