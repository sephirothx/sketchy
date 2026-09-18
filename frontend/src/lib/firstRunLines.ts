/**
 * The line the lobby opens with (#590).
 *
 * The first thing a cold visitor reads is drawn from a pool rather than fixed:
 * the lobby is not the same page twice, and somebody who came back yesterday
 * gets a different joke. One line per visit - picked on the first render and
 * held for the life of the tab, so it does not change under a player who is
 * mid-sentence in the name field.
 *
 * The pool is per language and not a translation of the English one: the
 * misread-drawing line only works with a pair of words that are far apart in
 * *that* language, and a joke that does not land is worse than a plain
 * sentence. The subtitle under it never moves - it is the one place the game
 * is actually explained.
 *
 * What is held for the visit is therefore the *roll*, not the line it picked:
 * a reader who switches language gets that language's pool read at the same
 * place, on the next render. Holding the string left the old language's joke
 * on screen until the page was reloaded.
 */

import { ui } from "../content/ui/index.ts";

/** Which line this pool offers for a roll of `random` in [0, 1). */
export function pickLine(pool: readonly string[], random: number): string {
  if (pool.length === 0) return "";
  const index = Math.min(pool.length - 1, Math.max(0, Math.floor(random * pool.length)));
  return pool[index];
}

let roll: number | null = null;

/** This visit's line, in the language being read now. */
export function firstRunLine(): string {
  roll ??= Math.random();
  return pickLine(ui.firstRunIdentity.lines, roll);
}
