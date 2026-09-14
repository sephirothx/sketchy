import type { ReactNode } from "react";
import { CustomPromptsEditor } from "./CustomPromptsEditor";
import { PromptListPicker } from "./PromptListPicker";
import { LanguageFace, LanguagePicker } from "./LanguagePicker";
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
  scoringNameFor,
} from "../lib/roomSetup";
import {
  availablePromptLanguages,
  promptLanguageLabel,
  selectionForLanguage,
} from "../lib/promptLanguages";
import type { CustomPromptsAction, CustomPromptsState } from "../lib/customPrompts";
import type {
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PromptLanguage,
  PromptListSummary,
  ScoringMode,
} from "../types";
import { ui } from "../content/ui/index.ts";

/** Everything both surfaces set. Custom prompts travel beside it, because they
    are a reducer rather than a value. */
export interface RoomSetupValues {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  promptLanguage: PromptLanguage;
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
  /** Every list the host may choose from, in any language: what the language
      field offers, and what the prompts summary is read from. */
  loadedLists?: PromptListSummary[];
  /** A room's language is fixed at creation, so the editor shows it rather
      than offering it. */
  languageLocked?: boolean;
  /** A community list the host arrived with, so the picker knows a list the
      catalogue would not have told it about. */
  extraLists?: PromptListSummary[];
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
  loadedLists = [],
  languageLocked = false,
  extraLists,
}: RoomSetupFormProps) {
  const {
    name,
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
  } = values;

  const selectedLists = loadedLists.filter((list) => promptListSlugs.includes(list.slug));
  const languageOptions = availablePromptLanguages(loadedLists, promptLanguage);

  const promptsSummary = (() => {
    const parts: string[] = [promptLanguageLabel(promptLanguage)];
    if (selectedLists.length > 0) {
      const names = selectedLists.map((list) => list.name);
      parts.push(names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", "));
      const total = selectedLists.reduce((sum, list) => sum + list.promptCount, 0);
      if (total > 0) parts.push(ui.roomSetupForm.promptTotal({ count: total }));
    }
    if (customPrompts.analysis.usableCount > 0) {
      parts.push(ui.roomSetupForm.customCount({ count: customPrompts.analysis.usableCount }));
    }
    return parts.join(" · ");
  })();

  const drawingSummary = [
    TOOL_GROUP_OPTIONS.filter((option) => allowedTools.includes(option.value))
      .map((option) => option.label)
      .join(", "),
    COLOR_MODE_OPTIONS.find((option) => option.value === colorMode)?.label ?? ui.roomSetupForm.allColors,
  ].filter(Boolean).join(" · ");

  const scoringSummary = `${scoringMode === "none" ? ui.roomSetupForm.noScoring : scoringNameFor(scoringMode)} · ${hintLabelFor(hintMode, hideMaskedPrompt)}`;
  const hintsDisabled = hideMaskedPrompt || scoringMode === "none";

  return (
    <div className="create-room-sections">
      <section className="form-section">
        <div className="form-section-head">
          <h2>{ui.roomSetupForm.basics}</h2>
        </div>
        <div className="form-section-body">
          <div className="create-room-name-row">
            <label className="create-room-name-field">
              {ui.roomSetupForm.roomName}
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
            <div className="create-room-language-field">
              {languageLocked ? (
                // The same face the picker wears, without the mechanism: a room
                // that cannot change its language still looks like the control
                // that set it.
                <span className="language-picker-static">
                  <LanguageFace value={promptLanguage} />
                </span>
              ) : (
                <LanguagePicker
                  label={ui.roomSetupForm.language}
                  flagOnly
                  value={promptLanguage}
                  options={languageOptions}
                  onChange={(next) => onChange({
                    promptLanguage: next as PromptLanguage,
                    // Lists cannot span languages, and the bearer codes that
                    // authorized the old ones belong to the language being
                    // left, so neither carries over.
                    promptListSlugs: selectionForLanguage(loadedLists, next),
                    promptListShareCodes: [],
                  })}
                />
              )}
            </div>
            {/* No caption and no hint button beside it: the pair is two words
                and two icons. The sentence they replaced stays as the control's
                own tooltip, because a lock says "restricted" rather than
                "share the code". */}
            <div
              className="visibility-field"
              title={isPublic
                ? ui.roomSetupForm.listedInTheLobbyAnyone
                : ui.roomSetupForm.joinableOnlyWithTheCode}
            >
              <SegmentedControl
                label={ui.roomSetupForm.visibility}
                value={isPublic ? "public" : "private"}
                onChange={(value) => onChange({ isPublic: value === "public" })}
                options={[
                  { value: "public", label: <><GlobeIcon size={14} />{ui.roomSetupForm.public}</> },
                  { value: "private", label: <><LockIcon size={14} />{ui.roomSetupForm.private}</> },
                ]}
              />
            </div>
          </div>
          <div className="setting-cards">
            {/* No hints under these three. The ranges are enforced by the
                controls themselves, "everyone draws once per round" is what a
                round is, and the line below already says what the three of
                them add up to in minutes. */}
            <InputNumber
              label={ui.roomSetupForm.maxPlayers}
              icon={<UsersIcon size={14} />}
              value={maxPlayers}
              min={MAX_PLAYERS_MIN}
              max={MAX_PLAYERS_MAX}
              onChange={(value) => onChange({ maxPlayers: value })}
            />
            <InputNumber
              label={ui.roomSetupForm.rounds}
              icon={<RoundsIcon size={14} />}
              value={rounds}
              min={ROUNDS_MIN}
              max={ROUNDS_MAX}
              onChange={(value) => onChange({ rounds: value })}
            />
            <InputNumber
              label={ui.roomSetupForm.drawingTime}
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
          <h2>{ui.roomSetupForm.prompts}</h2>
          {promptsSummary && <span className="form-section-summary">{promptsSummary}</span>}
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <PromptListPicker
            language={promptLanguage}
            selectedSlugs={promptListSlugs}
            onChange={(slugs) => onChange({ promptListSlugs: slugs })}
            shareCodes={promptListShareCodes}
            onShareCodesChange={(codes) => onChange({ promptListShareCodes: codes })}
            onListsLoaded={onListsLoaded}
            extraLists={extraLists}
          />
          <CustomPromptsEditor
            value={customPrompts.value}
            analysis={customPrompts.analysis}
            onChange={(value) => dispatchCustomPrompts({ type: "change", value })}
            footer={promptsFooter}
          />
          <Switch
            label={ui.roomSetupForm.onlyUseCustomPrompts}
            hint={ui.roomSetupForm.addUsableCustomPromptEnableThis}
            checked={customPrompts.only}
            disabled={customPrompts.analysis.usableCount === 0 || customPrompts.analysis.hasErrors}
            onChange={(only) => dispatchCustomPrompts({ type: "set-only", only })}
          />
        </div>
      </details>

      <details className="form-section is-collapsible">
        <summary>
          <h2>{ui.roomSetupForm.drawing}</h2>
          <span className="form-section-summary">{drawingSummary}</span>
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <ToggleChips
            label={ui.roomSetupForm.allowedTools}
            values={allowedTools}
            onChange={(tools: DrawingToolGroup[]) => onChange({ allowedTools: tools })}
            options={TOOL_GROUP_OPTIONS.map((option) => ({
              ...option,
              disabled: !canDisallowTool(option.value, allowedTools),
            }))}
          />
          <ChoiceCards
            label={ui.roomSetupForm.colors}
            value={colorMode}
            onChange={(mode: ColorMode) => onChange({ colorMode: mode })}
            columns={4}
            options={COLOR_MODE_OPTIONS}
          />
        </div>
      </details>

      <details className="form-section is-collapsible">
        <summary>
          <h2>{ui.roomSetupForm.scoringHints}</h2>
          <span className="form-section-summary">{scoringSummary}</span>
          <span className="form-section-chevron" aria-hidden="true"><ChevronRightIcon size={16} /></span>
        </summary>
        <div className="form-section-body">
          <ChoiceCards
            label={ui.roomSetupForm.scoring}
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
            label={ui.roomSetupForm.hints}
            value={hintMode}
            columns={2}
            disabled={hideMaskedPrompt}
            onChange={(mode: HintMode) => onChange({ hintMode: mode })}
            options={HINT_OPTIONS.map((option) => ({
              ...option,
              disabled: scoringMode === "none" && (option.value === "purchase" || option.value === "wheel"),
            }))}
          />
          {hideMaskedPrompt && <p className="setting-dependency">{ui.roomSetupForm.hintsAreOffBecauseBlanksAre}</p>}
          {hintsDisabled && !hideMaskedPrompt && <p className="setting-dependency">{ui.roomSetupForm.pointPurchaseHintModesRequireScoring}</p>}
          <div className="form-section-switch-row">
            <Switch
              label={ui.roomSetupForm.spectatorsCanSeePrompt}
              checked={spectatorsSeePrompt}
              onChange={(checked) => onChange({ spectatorsSeePrompt: checked })}
            />
            <Switch
              label={ui.roomSetupForm.hideBlanks}
              hint={ui.roomSetupForm.alsoTurnsHintsOffWithNo}
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
