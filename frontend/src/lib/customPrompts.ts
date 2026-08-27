// Mirrors backend/app/prompts.py. A room holds these in memory for its whole
// life, so the ceiling is what one room should cost, not what one message can
// carry; a large curated set belongs in an owned prompt list instead.
export const MAX_CUSTOM_PROMPTS = 2_000;
export const MAX_PROMPT_LENGTH = 32;
export const MAX_RAW_INPUT_LENGTH = 80_000;

export interface CustomPromptAnalysis {
  usableCount: number;
  duplicateCount: number;
  invalidEntries: string[];
  overLimitCount: number;
  hasErrors: boolean;
}

export interface CustomPromptsState {
  value: string;
  analysis: CustomPromptAnalysis;
  only: boolean;
}

export type CustomPromptsAction =
  | { type: "change"; value: string }
  | { type: "reset"; value: string; only: boolean }
  | { type: "set-only"; only: boolean };

export function analyzeCustomPrompts(raw: string): CustomPromptAnalysis {
  const seen = new Set<string>();
  const invalidEntries: string[] = [];
  let usableCount = 0;
  let duplicateCount = 0;
  let overLimitCount = 0;

  for (const part of raw.split(/[\n\r,]+/)) {
    const prompt = part.trim();
    if (!prompt) continue;
    if (prompt.length > MAX_PROMPT_LENGTH) {
      invalidEntries.push(prompt);
      continue;
    }
    const key = prompt.toLowerCase();
    if (seen.has(key)) {
      duplicateCount += 1;
      continue;
    }
    seen.add(key);
    if (usableCount >= MAX_CUSTOM_PROMPTS) {
      overLimitCount += 1;
      continue;
    }
    usableCount += 1;
  }

  return {
    usableCount,
    duplicateCount,
    invalidEntries,
    overLimitCount,
    hasErrors: invalidEntries.length > 0 || overLimitCount > 0,
  };
}

function canUseCustomPromptsOnly(analysis: CustomPromptAnalysis) {
  return analysis.usableCount > 0 && !analysis.hasErrors;
}

export function createCustomPromptsState(
  value = "",
  only = false,
): CustomPromptsState {
  const analysis = analyzeCustomPrompts(value);
  return {
    value,
    analysis,
    only: canUseCustomPromptsOnly(analysis) && only,
  };
}

export function customPromptsReducer(
  state: CustomPromptsState,
  action: CustomPromptsAction,
): CustomPromptsState {
  if (action.type === "set-only") {
    const only = canUseCustomPromptsOnly(state.analysis) && action.only;
    return only === state.only ? state : { ...state, only };
  }
  if (action.type === "change" && action.value === state.value) return state;
  const only = action.type === "reset" ? action.only : state.only;
  return createCustomPromptsState(action.value, only);
}
