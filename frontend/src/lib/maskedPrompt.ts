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
