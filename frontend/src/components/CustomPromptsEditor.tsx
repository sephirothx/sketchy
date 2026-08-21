import { MAX_CUSTOM_PROMPTS, MAX_RAW_INPUT_LENGTH, MAX_PROMPT_LENGTH } from "../lib/customPrompts";
import type { CustomPromptAnalysis } from "../lib/customPrompts";

interface CustomPromptsEditorProps {
  value: string;
  analysis: CustomPromptAnalysis;
  onChange: (value: string) => void;
}

export function CustomPromptsEditor({ value, analysis, onChange }: CustomPromptsEditorProps) {
  return <div className="custom-prompts-editor">
    <label htmlFor="custom-prompts">Custom prompts (optional)</label>
    <textarea id="custom-prompts" value={value} onChange={(event) => onChange(event.target.value)}
      placeholder={"One prompt per line\nor separate entries with commas"}
      maxLength={MAX_RAW_INPUT_LENGTH} rows={7} aria-describedby="custom-prompts-summary" />
    <div id="custom-prompts-summary" className={analysis.hasErrors ? "custom-prompts-summary has-errors" : "custom-prompts-summary"} aria-live="polite">
      <strong>{analysis.usableCount} usable custom prompt{analysis.usableCount === 1 ? "" : "s"}</strong>
      {analysis.duplicateCount > 0 && <span>{analysis.duplicateCount} duplicate{analysis.duplicateCount === 1 ? "" : "s"} ignored</span>}
      {analysis.invalidEntries.length > 0 && <span>{analysis.invalidEntries.length} entr{analysis.invalidEntries.length === 1 ? "y is" : "ies are"} over {MAX_PROMPT_LENGTH} characters</span>}
      {analysis.overLimitCount > 0 && <span>Only {MAX_CUSTOM_PROMPTS.toLocaleString()} entries are allowed</span>}
    </div>
    {analysis.invalidEntries.length > 0 && <p className="custom-prompts-error">Shorten or remove overlong entries before creating the room.</p>}
  </div>;
}
