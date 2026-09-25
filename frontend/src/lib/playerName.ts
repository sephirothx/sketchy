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

/** A player-list cell as it is measured: its unrounded border-box width and
 * the insets inside it. */
export interface NameCell {
  width: number;
  borderLeft: number;
  borderRight: number;
  paddingLeft: number;
  paddingRight: number;
}

/**
 * The font size that fits a name on one line of its player-list cell, or
 * `null` when it already fits at the size it has.
 *
 * The name may have the cell's content box, not its padding: the padding is
 * the room for ink past the letters (--ink-overhang, #1170), and a name
 * fitted into it is cut by the ellipsis instead. The width is the unrounded
 * one - `clientWidth` rounds, and a name fitted a fraction wider than its
 * box also ends in an ellipsis - and the size is rounded down to a tenth of
 * a pixel so the fitted text lands inside rather than on the edge.
 */
export function fittedNameFontSize(
  cell: NameCell,
  naturalWidth: number,
  fontSize: number,
): number | null {
  const available =
    cell.width - cell.borderLeft - cell.borderRight - cell.paddingLeft - cell.paddingRight;
  if (available <= 0 || naturalWidth <= available) return null;
  return Math.floor((available / naturalWidth) * fontSize * 10) / 10;
}
