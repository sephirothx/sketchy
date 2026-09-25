/** The phone bar's round chip, in every interface language (R-UX-11).

The chip shows "Round 2/3" when the bar has room and "2/3" when it does not
(GameHeaderStatus measures which). Both come from the catalogue, so this pins
what a translation has to keep: the short form is the numbers alone, and the
full one is a word in front of it - never an abbreviation such as "R2/3",
which read as a code.
*/
import assert from "node:assert/strict";
import test from "node:test";

import {
  CATALOGUE_LOCALES,
  catalogueFor,
  loadCatalogue,
} from "../src/content/ui/index.ts";

await Promise.all(CATALOGUE_LOCALES.map(loadCatalogue));

// Rooms run 1 to 10 rounds (`rounds` in backend/app/handlers/payloads.py).
const ROUNDS = [];
for (let totalRounds = 1; totalRounds <= 10; totalRounds += 1) {
  for (let roundNumber = 1; roundNumber <= totalRounds; roundNumber += 1) {
    ROUNDS.push({ roundNumber, totalRounds });
  }
}

test("the full label is a word and the short one, never an abbreviation", () => {
  for (const locale of CATALOGUE_LOCALES) {
    const { gameHeaderStatus } = catalogueFor(locale);
    for (const round of ROUNDS) {
      const full = gameHeaderStatus.roundCompact(round);
      const short = gameHeaderStatus.roundFraction(round);
      assert.equal(short, `${round.roundNumber}/${round.totalRounds}`, locale);
      assert.ok(full.endsWith(` ${short}`), `${locale}: "${full}" does not end in "${short}"`);
      assert.match(full.slice(0, -short.length - 1), /^\p{L}{4,}$/u, `${locale}: "${full}"`);
    }
  }
});
