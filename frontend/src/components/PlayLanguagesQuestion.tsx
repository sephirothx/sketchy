import { LanguagePicker } from "./LanguagePicker";
import { PlayLanguageExtras, PlayLanguageSuggestions } from "./PlayLanguageExtras";
import { ModalShell } from "./ui/ModalShell";
import { usePlayLanguages } from "../hooks/usePlayLanguages";
import { SUPPORTED_PROMPT_LANGUAGES } from "../lib/promptLanguages";
import type { PromptLanguage } from "../types";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/play-languages.css";

/**
 * Which languages a first-time player plays in, asked once (#1219): the
 * default, the others ranked, and the browser's other languages offered -
 * Settings' own rows and labels, pre-filled from the browser, so the place
 * the note sends them to looks like what they answered. No hint under
 * either: the title asks the question and the labels answer it.
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
            <b>{ui.settingsOverlay.languageYouPlay}</b>
          </span>
          <LanguagePicker
            label={ui.settingsOverlay.languageYouPlay}
            value={playLanguages.promptLanguage}
            options={SUPPORTED_PROMPT_LANGUAGES}
            onChange={(next) => playLanguages.chooseDefault(next as PromptLanguage)}
          />
        </div>
        <div className="play-languages-question-row">
          <span className="play-languages-question-label">
            <b>{ui.settingsOverlay.alsoPlayIn}</b>
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
