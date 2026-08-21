/**
 * Presentation rules for a player's name.
 *
 * Guests never carry a chosen color: they are rendered from the stylesheet so
 * the grey can differ per theme and stay above the 4.5:1 contrast floor, which
 * a single server-supplied hex could not do on both light and dark surfaces.
 */
export function playerNameClass(isAnonymous?: boolean, extra?: string): string {
  const base = isAnonymous ? "colored-player-name is-guest" : "colored-player-name";
  return extra ? `${base} ${extra}` : base;
}

export function playerNameStyle(
  nameColor: string | undefined,
  isAnonymous?: boolean,
): { color?: string } {
  return isAnonymous ? {} : { color: nameColor };
}
