import { formattersFor } from "../ui/format.ts";
import type { SeoCopy } from "./types.ts";

/** The descriptions, in English: the reference the others translate.

Written for somebody deciding which search result to open. They use the words
people search for - "drawing and guessing game", and "Pictionary" as a
comparison, never as a name (#1457) - and say what is on the page. */
const { counted } = formattersFor("en");

export const SEO_EN: SeoCopy = {
  locale: "en",
  home:
    "A free online drawing and guessing game, like Pictionary. Play with friends in your " +
    "browser: no account, no download.",
  rules:
    "The rules that keep Sketchy fun: how you treat other players, what you draw and write, fair play, and what happens when a rule is broken.",
  terms:
    "The terms for playing Sketchy: who may play, accounts, what you draw and write, " +
    "moderation, and leaving.",
  privacy:
    "What Sketchy keeps about you, why, for how long, and what you can do about it. No " +
    "advertising, and nothing about you is sold.",
  solo:
    "Guess drawings from real games on your own: a new Daily every day, and free runs " +
    "whenever you like.",
  promptList: (p) =>
    `${counted(p.count, { one: "word", other: "words" })} from ${p.name} for drawing and ` +
    "guessing games like Pictionary, with how often players actually guess each one.",
};
