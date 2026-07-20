// The backend renders maskedWord as e.g. "_ _ _ _  _ _  _ _ _ _ _  4 2 5" -
// tightly spaced blanks per word, followed by each word's letter count (in
// order) at the very end. Digits only ever appear in that trailing count
// list, so splitting on the first digit cleanly separates the two parts.
export function splitMaskedWord(masked: string): { blanks: string; counts: string[] } {
  const digitIndex = masked.search(/\d/);
  if (digitIndex === -1) {
    return { blanks: masked, counts: [] };
  }
  const blanks = masked.slice(0, digitIndex).trimEnd();
  const counts = masked.slice(digitIndex).trim().split(/\s+/);
  return { blanks, counts };
}
