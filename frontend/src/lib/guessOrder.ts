/**
 * 1-based finishing place per player, from the seconds-since-turn-start the
 * store records for each correct guess. Ties keep the order the server sent
 * them in, which is the order they arrived.
 */
export function rankGuesses(turnCorrectGuesses: Record<string, number>): Record<string, number> {
  const entries = Object.entries(turnCorrectGuesses);
  entries.sort((a, b) => a[1] - b[1]);
  const places: Record<string, number> = {};
  entries.forEach(([playerId], index) => {
    places[playerId] = index + 1;
  });
  return places;
}
