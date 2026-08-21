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

