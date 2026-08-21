import { MAX_CUSTOM_WORDS, MAX_RAW_INPUT_LENGTH, MAX_WORD_LENGTH } from "../lib/customWords";
import type { CustomWordAnalysis } from "../lib/customWords";

interface CustomWordsEditorProps {
  value: string;
  analysis: CustomWordAnalysis;
  onChange: (value: string) => void;
}

export function CustomWordsEditor({ value, analysis, onChange }: CustomWordsEditorProps) {
  return <div className="custom-words-editor">
    <label htmlFor="custom-words">Custom prompts (optional)</label>
    <textarea id="custom-words" value={value} onChange={(event) => onChange(event.target.value)}
      placeholder={"One prompt per line\nor separate entries with commas"}
      maxLength={MAX_RAW_INPUT_LENGTH} rows={7} aria-describedby="custom-words-summary" />
    <div id="custom-words-summary" className={analysis.hasErrors ? "custom-words-summary has-errors" : "custom-words-summary"} aria-live="polite">
      <strong>{analysis.usableCount} usable custom prompt{analysis.usableCount === 1 ? "" : "s"}</strong>
      {analysis.duplicateCount > 0 && <span>{analysis.duplicateCount} duplicate{analysis.duplicateCount === 1 ? "" : "s"} ignored</span>}
      {analysis.invalidEntries.length > 0 && <span>{analysis.invalidEntries.length} entr{analysis.invalidEntries.length === 1 ? "y is" : "ies are"} over {MAX_WORD_LENGTH} characters</span>}
      {analysis.overLimitCount > 0 && <span>Only {MAX_CUSTOM_WORDS.toLocaleString()} entries are allowed</span>}
    </div>
    {analysis.invalidEntries.length > 0 && <p className="custom-words-error">Shorten or remove overlong entries before creating the room.</p>}
  </div>;
}
