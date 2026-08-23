import type { PromptLanguage, PromptListSummary } from "../types";
import type { PromptListDraftEntry } from "./promptLists";

export function promptEntriesFromQuickInput(raw: string | undefined): PromptListDraftEntry[] {
  // Nothing carried over means an empty list, not a blank row to fill in: the
  // editor adds prompts in batches rather than one input at a time.
  if (!raw) return [];
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

export const MAX_LIST_PROMPTS = 500;
export const MAX_LIST_PROMPT_LENGTH = 32;

export interface PromptMergeResult {
  entries: PromptListDraftEntry[];
  added: number;
  duplicates: number;
  tooLong: string[];
  overLimit: number;
}

/**
 * Fold pasted text into a list of prompts, one per line or comma separated.
 *
 * Merging rather than replacing is what lets a list be built from several
 * pastes. Duplicates are compared case-insensitively against everything
 * already in the list, not just within the pasted batch, so pasting the same
 * source twice is harmless.
 */
export function mergePromptEntries(
  existing: PromptListDraftEntry[],
  raw: string,
): PromptMergeResult {
  const entries = [...existing];
  const seen = new Set(entries.map((entry) => entry.prompt.toLocaleLowerCase()));
  const tooLong: string[] = [];
  let added = 0;
  let duplicates = 0;
  let overLimit = 0;

  for (const part of raw.split(/[\n\r,]+/)) {
    const prompt = part.trim();
    if (!prompt) continue;
    if (prompt.length > MAX_LIST_PROMPT_LENGTH) {
      tooLong.push(prompt);
      continue;
    }
    const key = prompt.toLocaleLowerCase();
    if (seen.has(key)) {
      duplicates += 1;
      continue;
    }
    if (entries.length >= MAX_LIST_PROMPTS) {
      overLimit += 1;
      continue;
    }
    seen.add(key);
    entries.push({ prompt, aliases: [] });
    added += 1;
  }

  return { entries, added, duplicates, tooLong, overLimit };
}

/** What the merge skipped, as one sentence, or null when it took everything. */
export function describePromptMerge(result: PromptMergeResult): string | null {
  const skipped: string[] = [];
  if (result.duplicates) {
    skipped.push(`${result.duplicates} already in the list`);
  }
  if (result.tooLong.length) {
    skipped.push(
      `${result.tooLong.length} over ${MAX_LIST_PROMPT_LENGTH} characters`,
    );
  }
  if (result.overLimit) {
    skipped.push(`${result.overLimit} past the ${MAX_LIST_PROMPTS} limit`);
  }
  if (!skipped.length) return null;
  const kept = result.added === 1 ? "Added 1 prompt" : `Added ${result.added} prompts`;
  return `${kept}; skipped ${skipped.join(", ")}.`;
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
