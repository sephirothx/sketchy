import type { PromptLanguage, PromptListSummary } from "../types";
import type { PromptListDraftEntry } from "./promptLists";

export function promptEntriesFromQuickInput(raw: string | undefined): PromptListDraftEntry[] {
  if (!raw) return [{ prompt: "", aliases: [] }];
  const seen = new Set<string>();
  return raw
    .split(/[\n\r,]+/)
    .map((prompt) => prompt.trim())
    .filter((prompt) => {
      const key = prompt.toLocaleLowerCase();
      if (!prompt || prompt.length > 32 || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 500)
    .map((prompt) => ({ prompt, aliases: [] }));
}

export function addSharedPromptSelection(
  selectedSlugs: string[],
  shareCodes: string[],
  shared: PromptListSummary,
  code: string,
  activeLanguage: PromptLanguage,
): { slugs: string[]; shareCodes: string[] } {
  const slugs = selectedSlugs.includes(shared.slug)
    ? selectedSlugs
    : shared.language === activeLanguage
      ? [...selectedSlugs, shared.slug]
      : [shared.slug];
  return {
    slugs,
    shareCodes: [...new Set([...shareCodes, code.trim()])],
  };
}
