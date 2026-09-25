/** The phone bar's round chip, in every interface language (R-UX-11).

The bar decides between "Round 2/3" and "2/3" with container queries sized
for the full label's length (`data-round-chars`, 9 to 12, in
`src/styles/game-room.css`), measured against the widest label of each length
the seven catalogues produce. A translation that made the label longer than
that, or put the numbers somewhere the short form does not, would overflow
the bar with nothing else to say so.
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

test("every language's full round label fits the lengths the bar is sized for", () => {
  for (const locale of CATALOGUE_LOCALES) {
    const { gameHeaderStatus } = catalogueFor(locale);
    for (const round of ROUNDS) {
      const label = gameHeaderStatus.roundCompact(round);
      assert.ok(label.length <= 12, `${locale}: "${label}" is longer than the bar allows for`);
    }
  }
});

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
