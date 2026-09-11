import type { PromptLanguage, PromptListSummary } from "../types";
import type { PromptListDraftEntry } from "./promptLists";
import { ui } from "../content/ui/index.ts";

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
    skipped.push(ui.promptListDrafts.duplicatesAlreadyInTheList({ duplicates: result.duplicates }));
  }
  if (result.tooLong.length) {
    skipped.push(
      ui.promptListDrafts.tooLongCountOverMaxListPrompt({ tooLongCount: result.tooLong.length, MAX_LIST_PROMPT_LENGTH }),
    );
  }
  if (result.overLimit) {
    skipped.push(ui.promptListDrafts.overLimitPastTheMaxList({ overLimit: result.overLimit, MAX_LIST_PROMPTS }));
  }
  if (!skipped.length) return null;
  const kept = ui.promptListDrafts.promptsAdded({ count: result.added });
  return ui.promptListDrafts.keptSkippedSkipped({ kept, skipped: skipped.join(", ") });
}

export type SharedPromptSelection =
  | { ok: true; slugs: string[]; shareCodes: string[] }
  | { ok: false; language: PromptLanguage };

/**
 * Fold a shared list into the room's selection, or refuse it.
 *
 * A shared list used to replace the whole selection when its language differed,
 * which quietly moved the room into that language. The room declares its
 * language now, so a list in another one is simply not for this room: the code
 * is not retained either, since it authorized nothing.
 */
export function addSharedPromptSelection(
  selectedSlugs: string[],
  shareCodes: string[],
  shared: PromptListSummary,
  code: string,
  roomLanguage: PromptLanguage,
): SharedPromptSelection {
  if (shared.language !== roomLanguage) {
    return { ok: false, language: shared.language };
  }
  return {
    ok: true,
    slugs: selectedSlugs.includes(shared.slug)
      ? selectedSlugs
      : [...selectedSlugs, shared.slug],
    shareCodes: [...new Set([...shareCodes, code.trim()])],
  };
}
