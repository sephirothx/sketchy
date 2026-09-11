import type { ReactNode } from "react";
import { MAX_CUSTOM_PROMPTS, MAX_RAW_INPUT_LENGTH, MAX_PROMPT_LENGTH } from "../lib/customPrompts";
import type { CustomPromptAnalysis } from "../lib/customPrompts";
import { ui } from "../content/ui/index.ts";

interface CustomPromptsEditorProps {
  value: string;
  analysis: CustomPromptAnalysis;
  onChange: (value: string) => void;
  /** The host has stopped editing - a good moment to store what they wrote. */
  onCommit?: () => void;
  /** Room rules put their explicit Apply control here; room creation does not. */
  footer?: ReactNode;
}

export function CustomPromptsEditor({ value, analysis, onChange, onCommit, footer }: CustomPromptsEditorProps) {
  return <div className="custom-prompts-editor">
    <label htmlFor="custom-prompts">{ui.customPromptsEditor.customPromptsOptional}</label>
    <textarea id="custom-prompts" value={value} onChange={(event) => onChange(event.target.value)}
      onBlur={onCommit}
      placeholder={ui.customPromptsEditor.onePromptPerLineSeparateEntries}
      maxLength={MAX_RAW_INPUT_LENGTH} rows={7} aria-describedby="custom-prompts-summary" />
    <div id="custom-prompts-summary" className={analysis.hasErrors ? "custom-prompts-summary has-errors" : "custom-prompts-summary"} aria-live="polite">
      <strong>{ui.customPromptsEditor.usableCount({ count: analysis.usableCount })}</strong>
      {analysis.duplicateCount > 0 && <span>{ui.customPromptsEditor.duplicatesIgnored({ count: analysis.duplicateCount })}</span>}
      {analysis.invalidEntries.length > 0 && <span>{ui.customPromptsEditor.entriesTooLong({ count: analysis.invalidEntries.length, limit: MAX_PROMPT_LENGTH })}</span>}
      {analysis.overLimitCount > 0 && <span>{ui.customPromptsEditor.entryLimit({ limit: MAX_CUSTOM_PROMPTS })}</span>}
    </div>
    {analysis.invalidEntries.length > 0 && <p className="custom-prompts-error">{ui.customPromptsEditor.shortenRemoveOverlongEntriesBeforeCreating}</p>}
    {footer}
  </div>;
}
