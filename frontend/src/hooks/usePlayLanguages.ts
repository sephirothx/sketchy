import { useState } from "react";

import { queueSettingsSync } from "../lib/accountSettingsSync";
import {
  chooseDefaultPlayLanguage,
  suggestedExtraPromptLanguages,
  type PlayLanguages,
} from "../lib/playLanguages";
import { useSettingsStore } from "../store/settingsStore";
import type { PromptLanguage } from "../types";

/** Browser languages this browser's player waved away as suggestions: kept
here, per browser, since the suggestion comes from this browser too. */
const DISMISSED_SUGGESTIONS_KEY = "sketchy_playlanguagesuggestions_dismissed";

function loadDismissedSuggestions(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(DISMISSED_SUGGESTIONS_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function saveDismissedSuggestions(languages: readonly string[]): void {
  try {
    localStorage.setItem(DISMISSED_SUGGESTIONS_KEY, JSON.stringify(languages));
  } catch {
    // No storage: the suggestion comes back next time, which is harmless.
  }
}

/**
 * The languages a player plays in, as every place that edits them edits them
 * (#1210): Settings, and the question a first-time player is asked (#1219).
 *
 * The default and the others are saved together: sent alone, a default the
 * server finds among the others would be swapped there (#1209), and this
 * copy would not know it.
 */
export function usePlayLanguages() {
  const promptLanguage = useSettingsStore((state) => state.promptLanguage);
  const extraPromptLanguages = useSettingsStore((state) => state.extraPromptLanguages);
  const setPlayLanguages = useSettingsStore((state) => state.setPlayLanguages);
  const [dismissed, setDismissed] = useState(loadDismissedSuggestions);

  function save(next: PlayLanguages) {
    setPlayLanguages(next);
    queueSettingsSync({
      promptLanguage: next.promptLanguage,
      extraPromptLanguages: next.extraPromptLanguages,
    });
  }

  const suggestions = suggestedExtraPromptLanguages(
    typeof navigator === "undefined" ? [] : navigator.languages,
    { promptLanguage, extraPromptLanguages },
    dismissed,
  );

  return {
    promptLanguage,
    extraPromptLanguages,
    suggestions,
    chooseDefault(next: PromptLanguage) {
      save(chooseDefaultPlayLanguage({ promptLanguage, extraPromptLanguages }, next));
    },
    chooseExtras(next: PromptLanguage[]) {
      save({ promptLanguage, extraPromptLanguages: next });
    },
    dismissSuggestions() {
      const next = [...dismissed, ...suggestions];
      setDismissed(next);
      saveDismissedSuggestions(next);
    },
  };
}
