// The backend renders maskedPrompt as e.g. "_ _ _ _  _ _  _ _ _ _ _  4 2 5" -
// tightly spaced blanks per word, followed by each word's letter count (in
// order) at the very end. A prompt can be several words long, which is why
// there is a run of blanks and a count per word rather than one of each.
// Digits only ever appear in that trailing count list, so splitting on the
// first digit cleanly separates the two parts.
export function splitMaskedPrompt(masked: string): { blanks: string; counts: string[] } {
  const digitIndex = masked.search(/\d/);
  if (digitIndex === -1) {
    return { blanks: masked, counts: [] };
  }
  const blanks = masked.slice(0, digitIndex).trimEnd();
  const counts = masked.slice(digitIndex).trim().split(/\s+/);
  return { blanks, counts };
}

/** One display cell of the masked prompt. A "slot" is a maskable letter or
 * digit (hidden while `char` is null); a "literal" is punctuation the backend
 * always leaves visible (hyphens, apostrophes). `slot` is the letter's global
 * index across the whole prompt - the same numbering `buy_hint` expects. */
export interface MaskedTile {
  kind: "slot" | "literal";
  char: string | null;
  slot: number | null;
}

export interface MaskedWord {
  tiles: MaskedTile[];
  /** The word's letter-run counts, in order. Punctuation splits a word into
   * several runs, so "spider-man" carries ["6", "3"]. */
  counts: string[];
}

// Matches the backend's ch.isalnum() closely enough for prompt content: any
// unicode letter or digit is a maskable slot; "_" is a slot still hidden.
const SLOT_CHAR = /[\p{L}\p{N}]/u;

/** Parse a masked prompt into per-word tiles with each word's letter-run
 * counts attached. Returns null when the string does not follow the
 * blanks-then-counts contract (e.g. "???" or a count/run mismatch), so
 * callers can fall back to rendering the raw string. */
export function maskedPromptWords(masked: string): MaskedWord[] | null {
  const { blanks, counts } = splitMaskedPrompt(masked);
  if (!blanks || counts.length === 0) return null;

  const words: MaskedWord[] = [];
  let slot = 0;
  let countIndex = 0;
  for (const wordText of blanks.split(/\s+/)) {
    if (!wordText) continue;
    const tiles: MaskedTile[] = [];
    let inRun = false;
    let runCount = 0;
    for (const char of wordText) {
      const isSlot = char === "_" || SLOT_CHAR.test(char);
      if (isSlot) {
        tiles.push({ kind: "slot", char: char === "_" ? null : char, slot });
        slot += 1;
        if (!inRun) {
          inRun = true;
          runCount += 1;
        }
      } else {
        tiles.push({ kind: "literal", char, slot: null });
        inRun = false;
      }
    }
    if (countIndex + runCount > counts.length) return null;
    words.push({ tiles, counts: counts.slice(countIndex, countIndex + runCount) });
    countIndex += runCount;
  }
  if (countIndex !== counts.length || words.length === 0) return null;
  return words;
}
