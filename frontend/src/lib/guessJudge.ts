/** Whether a guess names a prompt, and how near a wrong one came: the port
of `backend/app/guess_judge.py` and the folds of `backend/app/prompt_content.py`
it judges through.

Solo (#1434) plays locally: the server hands over the forms a drawing is
judged by (`SoloForms`), and the page tells the player "correct", "close" or
nothing without a round trip per guess. A room's guesses are judged by the
Python judge, so this one has to answer exactly as that one does, or a word
that wins in a room would lose in Solo. `fixtures/guess_judge_cases.json`
records the Python verdicts, and `tests/guessJudge.test.mjs` holds this port
to every one of them; change a rule on one side and both fail.

What a port has to reproduce, because JavaScript does it differently:

- Lengths and indices are counted in code points, as Python's `str` is, not
  UTF-16 units: everything below walks `Array.from(text)`.
- `str.split()` and the regular expressions' `\s` break on every character
  `str.isspace` accepts - \x1c-\x1f and \x85 among them, U+FEFF not - which
  is not JavaScript's `\s`. `SPACE` is Python's set, written out.
- `str.casefold` is not `toLowerCase`: "ß" folds to "ss", final "ς" to "σ",
  "ﬁ" to "fi", Cherokee to its capitals. `casefold` applies the code points
  where the two differ, from a table, and `toLowerCase` one code point at a
  time for the rest (a whole-string call would make "Σ" final-sigma aware).
- `_fold_accents` drops what `unicodedata.combining` calls a mark - a nonzero
  canonical combining class, which is not Unicode's Mark category, and which
  JavaScript has no API for: `COMBINING_RANGES` is the table.
- `difflib.SequenceMatcher(None, guess, target).ratio()` depends on which
  string comes second (it is the one indexed) and on how
  `find_longest_match` breaks ties; `difflibRatio` is a line-for-line port.
- `str.isalnum` is `\p{L}` or `\p{N}`: checked over every code point of
  Python 3.14's Unicode 16.0, the two sets are identical.

The tables were generated from Python 3.14's `unicodedata` (Unicode 16.0.0)
by a throwaway script that walked every code point. NFC and NFD come from the
engine's `String.prototype.normalize`, whose Unicode version may be newer;
the two agree on every character Unicode 16 assigns, since a published
normalization never changes. */

/** One language's prompt and the other spellings it accepts. */
export interface JudgeForm {
  prompt: string;
  aliases: string[];
}

/**
 * The prompt as one guesser plays it (Python `JudgeTarget`): `language`
 * folds the guesser's text and `own` is the prompt in it; `others` are the
 * forms in the other languages somebody in the game plays, each folded in its
 * own language; `taken` are spellings, in the guesser's fold, that mean a
 * different concept to them, so another language's form that is one of them
 * does not win (#1367). Structurally `SoloForms`, as the server sends it.
 */
export interface JudgeTarget {
  language: string;
  own: JudgeForm;
  others: Record<string, JudgeForm>;
  taken: string[];
}

export type Verdict = "correct" | "close" | "partial" | "another_language" | "held";

// `app.prompts.MAX_PROMPT_LENGTH`: no answer is longer, so a longer message is chat.
const MAX_PROMPT_LENGTH = 32;

// The near-miss constants of guess_judge.py; the reasoning is there.
const CLOSE_GUESS_MAX_DISTANCE = 2;
const CLOSE_GUESS_SIMILARITY_THRESHOLD = 0.75;
const CLOSE_GUESS_MIN_CORRECT_LETTERS = 5;
const HELD_VERDICT_MAX_EXTRA_WORDS = 1;

// `validate_prompt_list_language`'s languages: the room languages and `zxx`.
const LIST_LANGUAGES = new Set(["en", "de", "es", "fr", "it", "nl", "pt", "pl", "zxx"]);

// --- Python's character classes -------------------------------------------

// Every character `str.isspace` accepts, which is also what Python's `\s`
// matches in a `str` pattern.
// Not copy: a regular-expression character class, not words.
const SPACE = "\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const SPACE_RUN = new RegExp(`[${SPACE}]+`, "u");

const ALNUM = /^[\p{L}\p{N}]$/u;

// `prompt_content._INVISIBLE`, as written there. Each code point in it is
// one to drop on its own, so a combining one (U+034F, the variation
// selectors) beside another is not the misleading class the lint fears.
const INVISIBLE = new RegExp(
  // eslint-disable-next-line no-misleading-character-class
  "[\\u00ad\\u034f\\u0600-\\u0605\\u061c\\u06dd\\u070f\\u0890\\u0891\\u08e2" +
    "\\u115f\\u1160\\u17b4\\u17b5\\u180b-\\u180f\\u200b-\\u200f\\u202a-\\u202e" +
    "\\u2060-\\u206f\\u3164\\ufe00-\\ufe0f\\ufeff\\uffa0\\ufff0-\\ufffb" +
    "\\u{110bd}\\u{110cd}\\u{13430}-\\u{1343f}\\u{1bca0}-\\u{1bca3}" +
    "\\u{1d173}-\\u{1d17a}\\u{e0000}-\\u{e0fff}]",
  "gu",
);

// `_SEPARATORS`, `_SEPARATOR` and `_WORD_MARKS`, with Python's `\s`.
const SEPARATOR_CLASS = `[${SPACE}\\-\\u2010-\\u2015\\u2212.']`;
const SEPARATORS = new RegExp(`${SEPARATOR_CLASS}+`, "gu");
const SEPARATOR = new RegExp(`^${SEPARATOR_CLASS}$`, "u");
const WORD_MARKS = /[.']+/g;

// `_APOSTROPHES`: every mark a keyboard writes for the apostrophe (#1011).
const APOSTROPHES = /[’ʼ‘‛′´`＇]/g;

const SENTENCE_ENDS = new Set(Array.from('.,!?…¿¡()[]"«»“”„'));

// Code points whose canonical combining class is not zero, as hex ranges.
const COMBINING_RANGES =
  "300-34e,350-36f,483-487,591-5bd,5bf,5c1-5c2,5c4-5c5,5c7,610-61a,64b-65f,670," +
  "6d6-6dc,6df-6e4,6e7-6e8,6ea-6ed,711,730-74a,7eb-7f3,7fd,816-819,81b-823," +
  "825-827,829-82d,859-85b,897-89f,8ca-8e1,8e3-8ff,93c,94d,951-954,9bc,9cd,9fe," +
  "a3c,a4d,abc,acd,b3c,b4d,bcd,c3c,c4d,c55-c56,cbc,ccd,d3b-d3c,d4d,dca,e38-e3a," +
  "e48-e4b,eb8-eba,ec8-ecb,f18-f19,f35,f37,f39,f71-f72,f74,f7a-f7d,f80,f82-f84," +
  "f86-f87,fc6,1037,1039-103a,108d,135d-135f,1714-1715,1734,17d2,17dd,18a9," +
  "1939-193b,1a17-1a18,1a60,1a75-1a7c,1a7f,1ab0-1abd,1abf-1ace,1b34,1b44," +
  "1b6b-1b73,1baa-1bab,1be6,1bf2-1bf3,1c37,1cd0-1cd2,1cd4-1ce0,1ce2-1ce8,1ced," +
  "1cf4,1cf8-1cf9,1dc0-1dff,20d0-20dc,20e1,20e5-20f0,2cef-2cf1,2d7f,2de0-2dff," +
  "302a-302f,3099-309a,a66f,a674-a67d,a69e-a69f,a6f0-a6f1,a806,a82c,a8c4," +
  "a8e0-a8f1,a92b-a92d,a953,a9b3,a9c0,aab0,aab2-aab4,aab7-aab8,aabe-aabf,aac1," +
  "aaf6,abed,fb1e,fe20-fe2f,101fd,102e0,10376-1037a,10a0d,10a0f,10a38-10a3a," +
  "10a3f,10ae5-10ae6,10d24-10d27,10d69-10d6d,10eab-10eac,10efd-10eff," +
  "10f46-10f50,10f82-10f85,11046,11070,1107f,110b9-110ba,11100-11102," +
  "11133-11134,11173,111c0,111ca,11235-11236,112e9-112ea,1133b-1133c,1134d," +
  "11366-1136c,11370-11374,113ce-113d0,11442,11446,1145e,114c2-114c3," +
  "115bf-115c0,1163f,116b6-116b7,1172b,11839-1183a,1193d-1193e,11943,119e0," +
  "11a34,11a47,11a99,11c3f,11d42,11d44-11d45,11d97,11f41-11f42,1612f," +
  "16af0-16af4,16b30-16b36,16ff0-16ff1,1bc9e,1d165-1d169,1d16d-1d172," +
  "1d17b-1d182,1d185-1d18b,1d1aa-1d1ad,1d242-1d244,1e000-1e006,1e008-1e018," +
  "1e01b-1e021,1e023-1e024,1e026-1e02a,1e08f,1e130-1e136,1e2ae,1e2ec-1e2ef," +
  "1e4ec-1e4ef,1e5ee-1e5ef,1e8d0-1e8d6,1e944-1e94a";

// Where `str.casefold` differs from `str.lower` by one code point: inclusive
// ranges and the offset each adds.
const CASEFOLD_SHIFTS: readonly (readonly [number, number, number])[] = [
  [0xb5, 0xb5, 775],
  [0x17f, 0x17f, -268],
  [0x345, 0x345, 116],
  [0x3c2, 0x3c2, 1],
  [0x3d0, 0x3d0, -30],
  [0x3d1, 0x3d1, -25],
  [0x3d5, 0x3d5, -15],
  [0x3d6, 0x3d6, -22],
  [0x3f0, 0x3f0, -54],
  [0x3f1, 0x3f1, -48],
  [0x3f5, 0x3f5, -64],
  [0x13a0, 0x13f5, 0],
  [0x13f8, 0x13fd, -8],
  [0x1c80, 0x1c80, -6222],
  [0x1c81, 0x1c81, -6221],
  [0x1c82, 0x1c82, -6212],
  [0x1c83, 0x1c84, -6210],
  [0x1c85, 0x1c85, -6211],
  [0x1c86, 0x1c86, -6204],
  [0x1c87, 0x1c87, -6180],
  [0x1c88, 0x1c88, 35267],
  [0x1e9b, 0x1e9b, -58],
  [0x1fbe, 0x1fbe, -7173],
  [0xab70, 0xabbf, -38864],
];

// Where it differs by more than one: "code point:folded", comma-separated.
const CASEFOLD_EXPANSIONS =
  "df:ss,149:\u02bcn,1f0:j\u030c,390:\u03b9\u0308\u0301," +
  "3b0:\u03c5\u0308\u0301,587:\u0565\u0582,1e96:h\u0331,1e97:t\u0308," +
  "1e98:w\u030a,1e99:y\u030a,1e9a:a\u02be,1e9e:ss,1f50:\u03c5\u0313," +
  "1f52:\u03c5\u0313\u0300,1f54:\u03c5\u0313\u0301," +
  "1f56:\u03c5\u0313\u0342,1f80:\u1f00\u03b9,1f81:\u1f01\u03b9," +
  "1f82:\u1f02\u03b9,1f83:\u1f03\u03b9,1f84:\u1f04\u03b9," +
  "1f85:\u1f05\u03b9,1f86:\u1f06\u03b9,1f87:\u1f07\u03b9," +
  "1f88:\u1f00\u03b9,1f89:\u1f01\u03b9,1f8a:\u1f02\u03b9," +
  "1f8b:\u1f03\u03b9,1f8c:\u1f04\u03b9,1f8d:\u1f05\u03b9," +
  "1f8e:\u1f06\u03b9,1f8f:\u1f07\u03b9,1f90:\u1f20\u03b9," +
  "1f91:\u1f21\u03b9,1f92:\u1f22\u03b9,1f93:\u1f23\u03b9," +
  "1f94:\u1f24\u03b9,1f95:\u1f25\u03b9,1f96:\u1f26\u03b9," +
  "1f97:\u1f27\u03b9,1f98:\u1f20\u03b9,1f99:\u1f21\u03b9," +
  "1f9a:\u1f22\u03b9,1f9b:\u1f23\u03b9,1f9c:\u1f24\u03b9," +
  "1f9d:\u1f25\u03b9,1f9e:\u1f26\u03b9,1f9f:\u1f27\u03b9," +
  "1fa0:\u1f60\u03b9,1fa1:\u1f61\u03b9,1fa2:\u1f62\u03b9," +
  "1fa3:\u1f63\u03b9,1fa4:\u1f64\u03b9,1fa5:\u1f65\u03b9," +
  "1fa6:\u1f66\u03b9,1fa7:\u1f67\u03b9,1fa8:\u1f60\u03b9," +
  "1fa9:\u1f61\u03b9,1faa:\u1f62\u03b9,1fab:\u1f63\u03b9," +
  "1fac:\u1f64\u03b9,1fad:\u1f65\u03b9,1fae:\u1f66\u03b9," +
  "1faf:\u1f67\u03b9,1fb2:\u1f70\u03b9,1fb3:\u03b1\u03b9," +
  "1fb4:\u03ac\u03b9,1fb6:\u03b1\u0342,1fb7:\u03b1\u0342\u03b9," +
  "1fbc:\u03b1\u03b9,1fc2:\u1f74\u03b9,1fc3:\u03b7\u03b9," +
  "1fc4:\u03ae\u03b9,1fc6:\u03b7\u0342,1fc7:\u03b7\u0342\u03b9," +
  "1fcc:\u03b7\u03b9,1fd2:\u03b9\u0308\u0300,1fd3:\u03b9\u0308\u0301," +
  "1fd6:\u03b9\u0342,1fd7:\u03b9\u0308\u0342,1fe2:\u03c5\u0308\u0300," +
  "1fe3:\u03c5\u0308\u0301,1fe4:\u03c1\u0313,1fe6:\u03c5\u0342," +
  "1fe7:\u03c5\u0308\u0342,1ff2:\u1f7c\u03b9,1ff3:\u03c9\u03b9," +
  "1ff4:\u03ce\u03b9,1ff6:\u03c9\u0342,1ff7:\u03c9\u0342\u03b9," +
  "1ffc:\u03c9\u03b9,fb00:ff,fb01:fi,fb02:fl,fb03:ffi,fb04:ffl,fb05:st," +
  "fb06:st,fb13:\u0574\u0576,fb14:\u0574\u0565,fb15:\u0574\u056b," +
  "fb16:\u057e\u0576,fb17:\u0574\u056d";

function parseRanges(table: string): number[] {
  // Flat [start, end, start, end, ...], sorted, for a binary search.
  const bounds: number[] = [];
  for (const range of table.split(",")) {
    const [start, end = start] = range.split("-");
    bounds.push(Number.parseInt(start, 16), Number.parseInt(end, 16));
  }
  return bounds;
}

const COMBINING = parseRanges(COMBINING_RANGES);

const CASEFOLD = new Map<number, string>();
for (const [start, end, shift] of CASEFOLD_SHIFTS) {
  for (let point = start; point <= end; point += 1) {
    CASEFOLD.set(point, String.fromCodePoint(point + shift));
  }
}
for (const entry of CASEFOLD_EXPANSIONS.split(",")) {
  const colon = entry.indexOf(":");
  CASEFOLD.set(Number.parseInt(entry.slice(0, colon), 16), entry.slice(colon + 1));
}

function isCombining(character: string): boolean {
  const point = character.codePointAt(0) ?? 0;
  let low = 0;
  let high = COMBINING.length / 2 - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (point < COMBINING[middle * 2]) high = middle - 1;
    else if (point > COMBINING[middle * 2 + 1]) low = middle + 1;
    else return true;
  }
  return false;
}

function isAlnum(character: string): boolean {
  return ALNUM.test(character);
}

function isSeparator(character: string): boolean {
  return SEPARATOR.test(character);
}

/** `str.casefold`, one code point at a time. */
function casefold(text: string): string {
  if (isAscii(text)) return text.toLowerCase();
  let folded = "";
  for (const character of text) {
    folded += CASEFOLD.get(character.codePointAt(0) ?? 0) ?? character.toLowerCase();
  }
  return folded;
}

/** `str.split()`: the words between runs of whitespace, none empty. */
function splitWords(text: string): string[] {
  return text.split(SPACE_RUN).filter((word) => word !== "");
}

/** `" ".join(text.split())`. */
function collapseSpace(text: string): string {
  return splitWords(text).join(" ");
}

function codePointLength(text: string): number {
  return Array.from(text).length;
}

/** `str.isascii`. */
function isAscii(text: string): boolean {
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) > 0x7f) return false;
  }
  return true;
}

// --- prompt_content.py ------------------------------------------------------

function listLanguage(language: string): string {
  if (LIST_LANGUAGES.has(language)) return language;
  const normalized = language.replace(new RegExp(`^[${SPACE}]+|[${SPACE}]+$`, "gu"), "").toLowerCase();
  if (LIST_LANGUAGES.has(normalized)) return normalized;
  throw new Error(`prompt language is not supported: ${language}`);
}

/** `_collapsed`: invisible characters dropped, whitespace collapsed, case
    folded, composed, apostrophes made plain - in that order. */
function collapsed(answer: string): string {
  const visible = isAscii(answer) ? answer : answer.replace(INVISIBLE, "");
  return casefold(collapseSpace(visible)).normalize("NFC").replace(APOSTROPHES, "'");
}

/** `_fold_accents`: whatever has a nonzero combining class after NFD goes. */
function foldAccents(text: string): string {
  if (isAscii(text)) return text;
  let folded = "";
  for (const character of text.normalize("NFD")) {
    if (!isCombining(character)) folded += character;
  }
  return folded;
}

const TRANSLITERATIONS: Record<string, Record<string, string>> = {
  de: { "ä": "ae", "ö": "oe", "ü": "ue" },
  fr: { "œ": "oe", "æ": "ae" },
  nl: { "ĳ": "ij" },
  pl: { "ł": "l" },
};

function transliterate(text: string, language: string): string {
  const table = TRANSLITERATIONS[language];
  if (table === undefined) return text;
  let written = "";
  for (const character of text) written += table[character] ?? character;
  return written;
}

const AMPERSAND_WORDS: Record<string, string> = {
  en: "and", de: "und", es: "y", fr: "et", it: "e", nl: "en", pl: "i", pt: "e",
};

function spelledOut(text: string, language: string): string {
  const word = AMPERSAND_WORDS[language];
  if (word === undefined || !text.includes("&")) return text;
  return collapseSpace(text.replaceAll("&", ` ${word} `));
}

function withoutSeparators(text: string): string {
  return text.replace(SEPARATORS, "");
}

/** The canonical comparison key of `answer` (`prompt_match_key`). */
export function promptMatchKey(answer: string, language: string): string {
  const canonical = listLanguage(language);
  const folded = spelledOut(collapsed(answer), canonical);
  return withoutSeparators(foldAccents(transliterate(folded, canonical)));
}

/** `prompt_match_words`: the key with each run of separators one space. */
export function promptMatchWords(answer: string, language: string): string {
  const canonical = listLanguage(language);
  const folded = foldAccents(transliterate(spelledOut(collapsed(answer), canonical), canonical));
  // A dot or an apostrophe sits inside a word; a hyphen or a space is between two.
  return collapseSpace(folded.replace(WORD_MARKS, "").replace(SEPARATORS, " "));
}

/** `prompt_match_variants`: the transliterated and the plainly folded key. */
export function promptMatchVariants(answer: string, language: string): Set<string> {
  const canonical = listLanguage(language);
  const folded = spelledOut(collapsed(answer), canonical);
  return new Set([
    withoutSeparators(foldAccents(transliterate(folded, canonical))),
    withoutSeparators(foldAccents(folded)),
  ]);
}

/** `_words_of`, over code points: where each word starts, and the sentence
    punctuation at either end that is not counted as one. */
function wordsOf(folded: string[]): { starts: boolean[]; ends: [number, number][] } {
  const starts = folded.map((character, index) => {
    if (isSeparator(character)) return false;
    if (!isAlnum(character)) return true;
    return index === 0 || !isAlnum(folded[index - 1]);
  });
  const content: number[] = [];
  folded.forEach((character, index) => {
    if (!isSeparator(character)) content.push(index);
  });
  const ends: [number, number][] = [];
  if (content.length > 0) {
    let lead = 0;
    while (lead < content.length && SENTENCE_ENDS.has(folded[content[lead]])) lead += 1;
    let trail = content.length;
    while (trail > lead && SENTENCE_ENDS.has(folded[content[trail - 1]])) trail -= 1;
    if (lead) ends.push([content[0], content[lead - 1] + 1]);
    if (trail < content.length) ends.push([content[trail], content[content.length - 1] + 1]);
  }
  for (const [begin, finish] of ends) {
    for (let index = begin; index < finish; index += 1) starts[index] = false;
  }
  return { starts, ends };
}

function atAnEdge(folded: string[], kept: number[], position: number): boolean {
  if (position === 0 || position === kept.length) return true;
  const before = kept[position - 1];
  const after = kept[position];
  if (after - before > 1) return true; // a separator stood between them
  return !(isAlnum(folded[before]) && isAlnum(folded[after]));
}

/** `str.find` over code points. */
function findIn(haystack: string[], needle: string[], from: number): number {
  outer: for (let start = from; start + needle.length <= haystack.length; start += 1) {
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (haystack[start + offset] !== needle[offset]) continue outer;
    }
    return start;
  }
  return -1;
}

/** `prompt_match_extra_words`: whether `text` holds one of `spellings` at
    word edges, and how many words lie outside the fewest-worded hold. */
export function promptMatchExtraWords(
  text: string,
  language: string,
  spellings: ReadonlySet<string>,
): number | null {
  const canonical = listLanguage(language);
  const spelled = spelledOut(collapsed(text), canonical);
  const wanted = [...spellings].filter((spelling) => spelling !== "").map((spelling) => Array.from(spelling));
  let fewest: number | null = null;
  const folds = new Set([foldAccents(transliterate(spelled, canonical)), foldAccents(spelled)]);
  for (const foldedText of folds) {
    const folded = Array.from(foldedText);
    const kept: number[] = [];
    folded.forEach((character, index) => {
      if (!isSeparator(character)) kept.push(index);
    });
    const key = kept.map((index) => folded[index]);
    const { starts, ends } = wordsOf(folded);
    // How many words begin before each position of the folded text.
    const begun = [0];
    for (const wordStarts of starts) begun.push(begun[begun.length - 1] + (wordStarts ? 1 : 0));
    const words = begun[begun.length - 1];
    // How many characters that are not separators precede each position.
    const shown = [0];
    for (const character of folded) shown.push(shown[shown.length - 1] + (isSeparator(character) ? 0 : 1));

    for (const spelling of wanted) {
      let found = findIn(key, spelling, 0);
      while (found !== -1) {
        const end = found + spelling.length;
        if (atAnEdge(folded, kept, found) && atAnEdge(folded, kept, end)) {
          const first = kept[found];
          const after = kept[end - 1] + 1;
          let extra = words - (begun[after] - begun[first]);
          for (const [begin, finish] of ends) {
            if (begin < after && first < finish) {
              // The hold reaches into end punctuation: what it leaves there
              // could be candidates too.
              const overlap = shown[Math.min(finish, after)] - shown[Math.max(begin, first)];
              extra += shown[finish] - shown[begin] - overlap;
            }
          }
          if (fewest === null || extra < fewest) fewest = extra;
        }
        found = findIn(key, spelling, found + 1);
      }
    }
  }
  return fewest;
}

// --- difflib ---------------------------------------------------------------

/**
 * `difflib.SequenceMatcher(None, a, b).ratio()`, over code points.
 *
 * `b` is the indexed side, so the ratio is not symmetric: Python's
 * `_is_close_pair` passes the guess as `a`, and so must every caller here.
 * With no `isjunk` the junk set is empty, which leaves autojunk's "popular"
 * rule - an element filling more than 1% of a `b` of 200 or more - as the
 * only thing `find_longest_match` has to extend across. A close-pair target
 * is a folded answer within two characters of a guess of at most
 * `MAX_PROMPT_LENGTH`, so it never applies; it is kept so the port stays
 * the function it names.
 */
function difflibRatio(a: string[], b: string[]): number {
  const b2j = new Map<string, number[]>();
  b.forEach((element, index) => {
    const indices = b2j.get(element);
    if (indices === undefined) b2j.set(element, [index]);
    else indices.push(index);
  });
  if (b.length >= 200) {
    const ntest = Math.floor(b.length / 100) + 1;
    for (const [element, indices] of [...b2j]) {
      if (indices.length > ntest) b2j.delete(element);
    }
  }

  const findLongestMatch = (alo: number, ahi: number, blo: number, bhi: number): [number, number, number] => {
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
    let j2len = new Map<number, number>();
    for (let i = alo; i < ahi; i += 1) {
      const newj2len = new Map<number, number>();
      for (const j of b2j.get(a[i]) ?? []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const k = (j2len.get(j - 1) ?? 0) + 1;
        newj2len.set(j, k);
        if (k > bestsize) {
          besti = i - k + 1;
          bestj = j - k + 1;
          bestsize = k;
        }
      }
      j2len = newj2len;
    }
    // Extend across popular elements, which b2j no longer holds. (Python's
    // second pair of loops extends across junk, and there is none.)
    while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) {
      besti -= 1;
      bestj -= 1;
      bestsize += 1;
    }
    while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] === b[bestj + bestsize]) {
      bestsize += 1;
    }
    return [besti, bestj, bestsize];
  };

  let matches = 0;
  const queue: [number, number, number, number][] = [[0, a.length, 0, b.length]];
  while (queue.length > 0) {
    const [alo, ahi, blo, bhi] = queue.pop() as [number, number, number, number];
    const [i, j, k] = findLongestMatch(alo, ahi, blo, bhi);
    if (k) {
      matches += k;
      if (alo < i && blo < j) queue.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) queue.push([i + k, ahi, j + k, bhi]);
    }
  }
  const length = a.length + b.length;
  return length ? (2 * matches) / length : 1;
}

// --- guess_judge.py ---------------------------------------------------------

/** `_bounded_damerau_levenshtein` (optimal string alignment), over code
    points: `maxDistance + 1` once the distance is past the bound. */
function boundedDamerauLevenshtein(a: string[], b: string[], maxDistance: number): number {
  const overLimit = maxDistance + 1;
  if (a.join("") === b.join("")) return 0;
  if (Math.abs(a.length - b.length) > maxDistance) return overLimit;
  if (a.length === 0) return b.length <= maxDistance ? b.length : overLimit;
  if (b.length === 0) return a.length <= maxDistance ? a.length : overLimit;
  const lenB = b.length;

  let previousPrevious = new Map<number, number>();
  let previous = new Map<number, number>();
  for (let j = 0; j <= Math.min(lenB, maxDistance); j += 1) previous.set(j, j);
  for (let i = 1; i <= a.length; i += 1) {
    const chA = a[i - 1];
    const current = new Map<number, number>();
    const firstColumn = Math.max(0, i - maxDistance);
    const lastColumn = Math.min(lenB, i + maxDistance);
    if (firstColumn === 0) current.set(0, i);
    for (let j = Math.max(1, firstColumn); j <= lastColumn; j += 1) {
      const chB = b[j - 1];
      const insertCost = (current.get(j - 1) ?? overLimit) + 1;
      const deleteCost = (previous.get(j) ?? overLimit) + 1;
      const substituteCost = (previous.get(j - 1) ?? overLimit) + (chA !== chB ? 1 : 0);
      let best = Math.min(insertCost, deleteCost, substituteCost);
      if (i > 1 && j > 1 && chA === b[j - 2] && a[i - 2] === chB) {
        best = Math.min(best, (previousPrevious.get(j - 2) ?? overLimit) + 1);
      }
      current.set(j, Math.min(best, overLimit));
    }
    previousPrevious = previous;
    previous = current;
  }
  return previous.get(lenB) ?? overLimit;
}

/** `_is_close_pair`: whether `guess` is close to `target`. */
function isClosePair(guessText: string, targetText: string): boolean {
  const guess = Array.from(guessText);
  const target = Array.from(targetText);
  if (target.length < 3 || guess.length < 2 || guessText === targetText) return false;
  if (Math.abs(guess.length - target.length) > CLOSE_GUESS_MAX_DISTANCE) return false;
  const distance = boundedDamerauLevenshtein(guess, target, CLOSE_GUESS_MAX_DISTANCE);
  if (distance === 1) return true;
  if (distance <= CLOSE_GUESS_MAX_DISTANCE) {
    // The guess first: difflib indexes the second sequence.
    return difflibRatio(guess, target) >= CLOSE_GUESS_SIMILARITY_THRESHOLD;
  }
  return false;
}

function tally(words: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const word of words) counts.set(word, (counts.get(word) ?? 0) + 1);
  return counts;
}

/** `_near_miss`: "close" near a whole answer, "partial" with enough of a
    multi-word answer's words, else null. Both sides are `promptMatchWords`. */
function nearMiss(guess: string, answers: readonly string[]): Verdict | null {
  // Close is measured with the separators gone, as acceptance compares.
  if (answers.some((answer) => isClosePair(guess.replaceAll(" ", ""), answer.replaceAll(" ", "")))) {
    return "close";
  }
  const guessTokens = guess.split(" ");
  const guessCounts = tally(guessTokens);
  for (const answer of answers) {
    const wordTokens = answer.split(" ");
    if (wordTokens.length <= 1 || Math.abs(guessTokens.length - wordTokens.length) > 1) continue;
    // Bag of words: any order, duplicates capped at the lower count.
    let correctLetterCount = 0;
    for (const [word, count] of tally(wordTokens)) {
      correctLetterCount += codePointLength(word) * Math.min(count, guessCounts.get(word) ?? 0);
    }
    if (correctLetterCount >= CLOSE_GUESS_MIN_CORRECT_LETTERS) return "partial";
  }
  return null;
}

/** Whether a message is short enough to be judged as a guess at all
    (`fits_a_guess`): at most `MAX_PROMPT_LENGTH` code points with its
    whitespace collapsed (#1416). */
export function fitsAGuess(text: string): boolean {
  return codePointLength(collapseSpace(text)) <= MAX_PROMPT_LENGTH;
}

function spellingsOf(form: JudgeForm): string[] {
  return [form.prompt, ...form.aliases];
}

function intersects(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  for (const spelling of left) if (right.has(spelling)) return true;
  return false;
}

function unique(values: Iterable<string>): string[] {
  return [...new Set(values)];
}

/** The guesser's own answer and aliases, in their fold (`own_spellings`). */
function ownSpellings(target: JudgeTarget): Set<string> {
  const spellings = new Set<string>();
  for (const answer of spellingsOf(target.own)) {
    for (const spelling of promptMatchVariants(answer, target.language)) spellings.add(spelling);
  }
  return spellings;
}

/** Every spelling that wins: the guesser's own, and each other language's
    folded its own way, less what is taken (`accepted_spellings`). */
function acceptedSpellings(target: JudgeTarget): Set<string> {
  const spellings = ownSpellings(target);
  const taken = new Set(target.taken);
  for (const [other, form] of Object.entries(target.others)) {
    for (const answer of spellingsOf(form)) {
      for (const spelling of promptMatchVariants(answer, other)) {
        if (!taken.has(spelling)) spellings.add(spelling);
      }
    }
  }
  return spellings;
}

function spellsThePromptElsewhere(guessed: ReadonlySet<string>, target: JudgeTarget): boolean {
  return Object.entries(target.others).some(([other, form]) =>
    spellingsOf(form).some((answer) => intersects(guessed, promptMatchVariants(answer, other))),
  );
}

/** `_held_verdict`: whether a wrong guess holds the prompt as whole words,
    and what its author is told. */
function heldVerdict(text: string, target: JudgeTarget, accepted: ReadonlySet<string>): Verdict | null {
  const mine = new Set([...ownSpellings(target), ...accepted]);
  let extra = promptMatchExtraWords(text, target.language, mine);
  if (extra !== null) return extra <= HELD_VERDICT_MAX_EXTRA_WORDS ? "close" : "held";
  // Another language's word that is a different prompt to this guesser
  // (#1367): still the drawing to the seats playing it.
  const inPlay = new Set<string>();
  for (const [other, form] of Object.entries(target.others)) {
    for (const answer of spellingsOf(form)) {
      for (const spelling of promptMatchVariants(answer, other)) {
        if (!accepted.has(spelling)) inPlay.add(spelling);
      }
    }
  }
  extra = promptMatchExtraWords(text, target.language, inPlay);
  if (extra !== null) return extra <= HELD_VERDICT_MAX_EXTRA_WORDS ? "another_language" : "held";
  return null;
}

/**
 * What a guess is (Python `judge`): `"correct"`, or what its author is told
 * about a wrong one - `"close"`, `"partial"`, `"another_language"` or
 * `"held"`. `null` is a plain wrong guess, or chat when it does not
 * `fitsAGuess`.
 */
export function judge(text: string, target: JudgeTarget): Verdict | null {
  const guessed = promptMatchVariants(text, target.language);
  const accepted = acceptedSpellings(target);
  if (intersects(guessed, accepted)) return "correct";
  if (spellsThePromptElsewhere(guessed, target)) return "another_language";
  const held = heldVerdict(text, target, accepted);
  if (held !== null) return held;
  if (!fitsAGuess(text)) return null;
  const ownKeys = unique(spellingsOf(target.own).map((answer) => promptMatchWords(answer, target.language)));
  const verdict = nearMiss(promptMatchWords(text, target.language), ownKeys);
  if (verdict !== null) return verdict;
  // Near another language's spelling, measured in that language's fold: the
  // seats playing it would read their answer in the typo.
  for (const [other, form] of Object.entries(target.others)) {
    const answers = unique(spellingsOf(form).map((answer) => promptMatchWords(answer, other)));
    const otherVerdict = nearMiss(promptMatchWords(text, other), answers);
    if (otherVerdict !== null) return otherVerdict;
  }
  return null;
}
