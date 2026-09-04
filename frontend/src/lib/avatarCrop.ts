/**
 * The shape of a player's picture, shared by the browser that makes one and
 * the tests that check the arithmetic. No imports, so it loads anywhere.
 */
export const AVATAR_SIZE = 256;
export const MAX_AVATAR_BYTES = 128 * 1024;

/** The square a picture is cut down to: the largest one centred on it. */
export function centreSquare(width: number, height: number): {
  x: number;
  y: number;
  side: number;
} {
  const side = Math.min(width, height);
  return { x: Math.floor((width - side) / 2), y: Math.floor((height - side) / 2), side };
}
