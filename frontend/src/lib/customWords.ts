export const MAX_CUSTOM_WORDS = 10_000;
export const MAX_WORD_LENGTH = 32;
export const MAX_RAW_INPUT_LENGTH = 400_000;

export interface CustomWordAnalysis {
  usableCount: number;
  duplicateCount: number;
  invalidEntries: string[];
  overLimitCount: number;
  hasErrors: boolean;
}

export function analyzeCustomWords(raw: string): CustomWordAnalysis {
  const seen = new Set<string>();
  const invalidEntries: string[] = [];
  let usableCount = 0;
  let duplicateCount = 0;
  let overLimitCount = 0;

  for (const part of raw.split(/[\n\r,]+/)) {
    const word = part.trim();
    if (!word) continue;
    if (word.length > MAX_WORD_LENGTH) {
      invalidEntries.push(word);
      continue;
    }
    const key = word.toLowerCase();
    if (seen.has(key)) {
      duplicateCount += 1;
      continue;
    }
    seen.add(key);
    if (usableCount >= MAX_CUSTOM_WORDS) {
      overLimitCount += 1;
      continue;
    }
    usableCount += 1;
  }

  return {
    usableCount,
    duplicateCount,
    invalidEntries,
    overLimitCount,
    hasErrors: invalidEntries.length > 0 || overLimitCount > 0,
  };
}
