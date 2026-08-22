import type { PromptLanguage } from "../types";

export const PROMPT_LANGUAGE_LABELS: Record<PromptLanguage, string> = {
  de: "German",
  en: "English",
  es: "Spanish",
  fr: "French",
  it: "Italian",
  nl: "Dutch",
  pt: "Portuguese",
};

export function promptLanguageLabel(language: string): string {
  return PROMPT_LANGUAGE_LABELS[language as PromptLanguage] ?? language;
}
