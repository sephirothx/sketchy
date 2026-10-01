import type { EmailState } from "./accountRecovery";
import type { PromptListDraftEntry } from "./promptLists";
import type { OwnedPromptList, PromptListLanguage } from "../types";
import { PROMPT_LANGUAGE_LABELS } from "./promptLanguages.ts";
import { withoutInvisibleCharacters } from "./visibleText.ts";
import { ui } from "../content/ui/index.ts";

export function promptEntriesFromQuickInput(raw: string | undefined): PromptListDraftEntry[] {
  // Nothing carried over means an empty list, not a blank row to fill in: the
  // editor adds prompts in batches rather than one input at a time.
  if (!raw) return [];
  const seen = new Set<string>();
  return raw
    .split(/[\n\r,]+/)
    .map((prompt) => withoutInvisibleCharacters(prompt).trim())
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
    // Before the length and duplicate checks: "cat" and "cat" with a
    // zero-width space in it are one prompt, and the space is not a character
    // anybody typed (#1245).
    const prompt = withoutInvisibleCharacters(part).trim();
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

/** The most characters a name may hold, counted as the server counts them:
by code point, so an emoji is one and never half of one. */
const MAX_NAME_CHARACTERS = 64;

/** A list's name when it is duplicated, shortened to fit if it has to be.

Counted in code points, not UTF-16 units: `length` and `slice` would count an
emoji twice, shorten such a name more than the server needs, and could cut one
in half - a lone surrogate the server cannot store. */
export function duplicateName(name: string): string {
  const full = Array.from(ui.myPromptListsPage.duplicateName({ name }));
  if (full.length <= MAX_NAME_CHARACTERS) return full.join("");
  const characters = Array.from(name);
  const suffix = full.slice(characters.length);
  const kept = characters.slice(0, MAX_NAME_CHARACTERS - suffix.length).join("").trimEnd();
  return `${kept}${suffix.join("")}`;
}

/** What stands between this account and publishing, as far as its email goes.

Said before Publish is pressed; the server's gate is still the authority
(R-LIST-12). Null when nothing does, when the list is already published, or
when the state has not been read yet - an unknown is not a refusal.

Delivery is asked first: an address can be pending on a server that cannot
send the message confirming it, and "confirm the email we sent" would be false. */
export function emailPublishBlocker(
  state: EmailState | null,
  published: boolean,
): "no-address" | "pending" | "undeliverable" | null {
  if (published || !state || state.verified) return null;
  if (!state.deliveryConfigured) return "undeliverable";
  return state.pendingAddress ? "pending" : "no-address";
}

/** The language a new list opens on: the player's default play language
    (#1213), or English where that is not a language a list can be in - which
    a room's Mixed is, and prompts saved from a Create room form arrive with
    the room's language instead (MyPromptListsPage).

    A list's language cannot change after its first save (R-LIST-05), and every
    new list opened on English: a German player's first list, created without a
    look at the picker, was offered in English rooms and the English catalogue
    for good, and the only way back was to delete it (#1272). */
export function newListLanguage(playLanguage: string | null | undefined): PromptListLanguage {
  return playLanguage && playLanguage in PROMPT_LANGUAGE_LABELS ? (playLanguage as PromptListLanguage) : "en";
}

/** What Publish update would change for players (#1363): the saved working
copy against the live edition. Prompts are matched by concept, so a reworded
prompt is one change rather than a removal and an addition. */
export interface EditionChanges {
  added: string[];
  removed: string[];
  reworded: { from: string; to: string }[];
  name: boolean;
  description: boolean;
  tags: boolean;
}

interface EditionSide {
  name: string;
  description: string;
  tags: string[];
  prompts: { conceptId: string; prompt: string }[];
}

export function editionChanges(live: EditionSide, working: EditionSide): EditionChanges {
  const liveByConcept = new Map(live.prompts.map((entry) => [entry.conceptId, entry.prompt]));
  const workingConcepts = new Set(working.prompts.map((entry) => entry.conceptId));
  let added: string[] = [];
  const reworded: { from: string; to: string }[] = [];
  for (const entry of working.prompts) {
    const before = liveByConcept.get(entry.conceptId);
    if (before === undefined) added.push(entry.prompt);
    else if (before !== entry.prompt) reworded.push({ from: before, to: entry.prompt });
  }
  let removed = live.prompts.filter((entry) => !workingConcepts.has(entry.conceptId)).map((entry) => entry.prompt);
  // A word removed and typed in again is a new concept, but the same word to
  // a player: neither a removal nor an addition.
  const readded = new Set(added.filter((prompt) => removed.includes(prompt)));
  added = added.filter((prompt) => !readded.has(prompt));
  removed = removed.filter((prompt) => !readded.has(prompt));
  return {
    added,
    removed,
    reworded,
    name: live.name !== working.name,
    description: live.description !== working.description,
    tags: [...live.tags].sort().join(",") !== [...working.tags].sort().join(","),
  };
}

/** The changes as the confirmation says them, one sentence each; empty when
only the order moved. */
/** How many prompts each line names before it says how many more: a
replaced list of 500 would otherwise be a wall of text, read out whole as the
dialog's description. */
export const CHANGES_NAMED = 8;

function named(prompts: string[]): string {
  const shown = prompts.slice(0, CHANGES_NAMED).join(", ");
  return prompts.length > CHANGES_NAMED
    ? `${shown} ${ui.myPromptListsPage.andNMore({ count: prompts.length - CHANGES_NAMED })}`
    : shown;
}

export function describeEditionChanges(changes: EditionChanges): string[] {
  const words = ui.myPromptListsPage;
  const lines: string[] = [];
  if (changes.added.length) lines.push(words.promptsAdded({ count: changes.added.length, prompts: named(changes.added) }));
  if (changes.removed.length) lines.push(words.promptsRemoved({ count: changes.removed.length, prompts: named(changes.removed) }));
  if (changes.reworded.length) {
    lines.push(words.promptsReworded({
      count: changes.reworded.length,
      prompts: named(changes.reworded.map(({ from, to }) => `${from} → ${to}`)),
    }));
  }
  if (changes.name) lines.push(words.nameChanged);
  if (changes.description) lines.push(words.descriptionChanged);
  if (changes.tags) lines.push(words.tagsChanged);
  return lines;
}

/** Where a published list stands against what players see (#1363). `none`
for a private list. While an edition waits, the owner's next step is the
moderator's - unless they have changed the list since, which the waiting
edition does not hold: `changed-since-review`, and Publish update sends the
newer version in its place. */
export type EditionStatus =
  | "none" | "first-under-review" | "update-under-review" | "changed-since-review" | "changed" | "live";

export function publishedEditionStatus(
  list: Pick<OwnedPromptList, "visibility" | "liveEdition" | "pendingEdition" | "unpublishedChanges"> | null,
): EditionStatus {
  if (!list || list.visibility !== "public") return "none";
  if (list.pendingEdition) {
    if (list.unpublishedChanges) return "changed-since-review";
    return list.liveEdition ? "update-under-review" : "first-under-review";
  }
  if (!list.liveEdition) return "none";
  return list.unpublishedChanges ? "changed" : "live";
}
