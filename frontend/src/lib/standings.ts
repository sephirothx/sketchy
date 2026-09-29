const PLACEMENT_MEDALS = ["🥇", "🥈", "🥉"];

/**
 * Places for scores already ordered best-first, ties sharing a place.
 *
 * Standard competition ranking: equal scores take the same place, and the
 * places they crowd out are skipped — 1, 2, 2, 4, never 1, 2, 2, 3. Mirrors
 * `competition_ranks` in `app/game.py`, which is what the server writes into
 * game history and sends with every turn result. A screen that counted rows
 * instead would tell two level players they finished first and second.
 */
export function competitionRanks(sortedScores: number[]): number[] {
  const ranks: number[] = [];
  sortedScores.forEach((score, index) => {
    if (index > 0 && score === sortedScores[index - 1]) {
      ranks.push(ranks[ranks.length - 1]);
    } else {
      ranks.push(index + 1);
    }
  });
  return ranks;
}

/**
 * The medal or number shown against a place.
 *
 * Follows the place, not the row: two players tied for first both take gold and
 * no silver is awarded, which is the same answer the recorded standings give —
 * a shared first place counts as a win for both.
 */
export function placementLabel(rank: number): string {
  return PLACEMENT_MEDALS[rank - 1] ?? `#${rank}`;
}

/** Most winners the headline names before it counts them instead. */
export const MAX_NAMED_WINNERS = 3;

/**
 * Which headline a finished game has earned.
 *
 * Split out from the overlay because a shared first is the case nobody plays
 * on purpose: it turns up rarely, at random, and only in a real game, which
 * makes it the branch most likely to be wrong and least likely to be noticed.
 */
export function crownOutcome(
  winnerCount: number,
): "room" | "one" | "shared" | "many" {
  if (winnerCount <= 0) return "room";
  if (winnerCount === 1) return "one";
  return winnerCount > MAX_NAMED_WINNERS ? "many" : "shared";
}

/**
 * How many rows each standings row must start above or below its final seat,
 * so the slide animation lands it in place.
 *
 * Driven by row positions, never by the difference between two ranks. Those
 * are not the same number once ties exist: on the first turn of a game every
 * player is on zero and therefore ranked first, so a rank difference would
 * offset the second and third rows upward by one and two rows and stack the
 * whole list on top of itself.
 *
 * Entries come in already ordered by their new rank; ties are broken by that
 * same order on both sides, so a tie moves nobody.
 */
export function rowStartOffsets(
  entries: { playerId: string; previousRank: number }[],
): number[] {
  const previousOrder = [...entries].sort(
    (a, b) => a.previousRank - b.previousRank,
  );
  const previousRow = new Map(
    previousOrder.map((entry, index) => [entry.playerId, index]),
  );
  return entries.map(
    (entry, index) => (previousRow.get(entry.playerId) ?? index) - index,
  );
}

/**
 * Whether the standings had an order before this turn.
 *
 * False on the first turn of a game, where every player comes in on zero and
 * so shares first place. There is nothing to slide from and nobody has really
 * lost ground, so the rows are introduced rather than rearranged.
 */
export function hasPreviousOrder(
  entries: { previousRank: number }[],
): boolean {
  return entries.some((entry) => entry.previousRank !== entries[0].previousRank);
}

/**
 * The place and total a turn-results row shows: the ones it came in with
 * while it waits at its old place, the new ones once it slides (#1278).
 *
 * A row that printed its new place from the start read "#1, #3, #2" for the
 * two seconds before the rows moved, beside a players panel already in the
 * new order. Rows being introduced (the first turn) have no old place to
 * wait at, and show the new ones.
 */
export function shownStanding(
  entry: { previousRank: number; newRank: number; score: number; delta: number },
  waiting: boolean,
): { rank: number; total: number } {
  return waiting
    ? { rank: entry.previousRank, total: entry.score - entry.delta }
    : { rank: entry.newRank, total: entry.score };
}

/**
 * Whether a turn-results row stands at its old place, and so shows its old
 * numbers (`shownStanding`): only while the rows are rearranging and have not
 * slid yet. Never under reduced motion, where the rows are in their new order
 * from the first frame - old numbers there read "#1, #3, #2" top to bottom,
 * the very card this was meant to fix (review of #1278).
 */
export function waitsAtOldPlace(reordering: boolean, settled: boolean, reducedMotion: boolean): boolean {
  return reordering && !settled && !reducedMotion;
}

/** How long rearranging rows wait before they slide: two seconds to read the
    old standings, but never most of a short results phase - the rows would
    leave with the old numbers still on them. `phaseSeconds` is what is left
    of the phase when the card appears (0 when unknown). */
export function reorderHoldMs(phaseSeconds: number): number {
  return phaseSeconds > 0 ? Math.min(2000, Math.round(phaseSeconds * 400)) : 2000;
}

/** Milliseconds between one row entering and the next. */
export const ENTRANCE_STAGGER_MS = 110;

/**
 * When each row enters, lowest place first so the list builds up to the leader.
 *
 * Entries arrive in final order, best first, so the delays run backwards: the
 * last row starts immediately and the top row waits for everyone below it.
 */
export function entranceDelays(rowCount: number): number[] {
  return Array.from(
    { length: rowCount },
    (_value, index) => (rowCount - 1 - index) * ENTRANCE_STAGGER_MS,
  );
}

