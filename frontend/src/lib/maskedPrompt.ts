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

/** A run of letter slots, or the punctuation between two runs. */
export type MaskedSegment =
  | { kind: "tiles"; chars: string[] }
  | { kind: "glyph"; text: string };

/** A slot the mask can hide: a blank, or a revealed letter or digit. The
Unicode classes mirror the server's `str.isalnum` masking, so an accented
letter revealed in "città" stays a tile rather than becoming punctuation. */
export function isSlotChar(ch: string): boolean {
  return ch === "_" || /[\p{L}\p{N}]/u.test(ch);
}

/** The blanks, grouped the way the trailing counts were counted.

The server counts letters per **alphanumeric run**, with punctuation as a
boundary: "spider-man" reports "6 3", not "10". So each whitespace word is
split into alternating tile runs and glyph segments, and the tile runs -
across all words, in order - correspond 1:1 with the counts. Grouping by
whitespace alone renders "____-___" as one group and drops a count. */
export function maskedWords(blanks: string): MaskedSegment[][] {
  return blanks
    .trim()
    .split(/\s+/)
    .filter((word) => word.length > 0)
    .map((word) => {
      const segments: MaskedSegment[] = [];
      for (const ch of word) {
        const last = segments[segments.length - 1];
        if (isSlotChar(ch)) {
          if (last?.kind === "tiles") last.chars.push(ch);
          else segments.push({ kind: "tiles", chars: [ch] });
        } else {
          if (last?.kind === "glyph") last.text += ch;
          else segments.push({ kind: "glyph", text: ch });
        }
      }
      return segments;
    });
}
