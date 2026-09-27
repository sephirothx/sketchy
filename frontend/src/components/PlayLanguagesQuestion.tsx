import { LanguagePicker } from "./LanguagePicker";
import { PlayLanguageExtras, PlayLanguageSuggestions } from "./PlayLanguageExtras";
import { ModalShell } from "./ui/ModalShell";
import { usePlayLanguages } from "../hooks/usePlayLanguages";
import { SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import type { PromptLanguage } from "../types";
import { ui } from "../content/ui/index.ts";

/**
 * Which languages a first-time player plays in, asked once (#1219): the
 * default, the others ranked, and the browser's other languages offered -
 * the same controls Settings has, pre-filled from the browser.
 *
 * Nothing is required and nothing is lost by setting it aside: every change
 * is saved as it is made, as in Settings, so Done and Escape both keep what
 * is shown, and both close it for good.
 */
export function PlayLanguagesQuestion({ onDone }: { onDone: () => void }) {
  const playLanguages = usePlayLanguages();
  return (
    <ModalShell
      title={ui.playLanguagesQuestion.title}
      cardClassName="play-languages-question"
      testId="play-languages-question"
      onDismiss={onDone}
      dismissOnBackdrop={false}
      footer={
        <button type="button" className="btn btn-primary" onClick={onDone}>
          {ui.playLanguagesQuestion.done}
        </button>
      }
    >
      <div className="play-languages-question-body">
        <div className="play-languages-question-row">
          <span className="play-languages-question-label">
            <b>{ui.playLanguagesQuestion.mostly}</b>
            <small>{ui.playLanguagesQuestion.mostlyHint}</small>
          </span>
          <LanguagePicker
            label={ui.playLanguagesQuestion.mostly}
            value={playLanguages.promptLanguage}
            options={SUPPORTED_PROMPT_LANGUAGES}
            onChange={(next) => playLanguages.chooseDefault(next as PromptLanguage)}
          />
        </div>
        <div className="play-languages-question-row">
          <span className="play-languages-question-label">
            <b>{ui.playLanguagesQuestion.also}</b>
            <small>{ui.playLanguagesQuestion.alsoHint}</small>
          </span>
          <div className="play-language-editor">
            <PlayLanguageExtras
              defaultLanguage={playLanguages.promptLanguage}
              extras={playLanguages.extraPromptLanguages}
              onChange={playLanguages.chooseExtras}
            />
            <PlayLanguageSuggestions
              suggestions={playLanguages.suggestions}
              onAdd={(language) =>
                playLanguages.chooseExtras([...playLanguages.extraPromptLanguages, language])}
              onDismiss={playLanguages.dismissSuggestions}
            />
          </div>
        </div>
        <p className="play-languages-question-note">{ui.playLanguagesQuestion.changeLater}</p>
      </div>
    </ModalShell>
  );
}
