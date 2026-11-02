import { ui } from "../content/ui/index.ts";

/**
 * The doodle set a registered player wears instead of an initial (#579).
 *
 * A doodle is one of this deployment's own drawings, chosen by name: nothing
 * is uploaded, and the account stores `doodle:<name>`. Its URL points into the
 * sprite by fragment (`/avatars/doodles.svg#fox`), and every disc draws it
 * through `<use>` rather than `<img>` - an image cannot take the disc's ink,
 * and the ink is what keeps the player's name color on it.
 *
 * The picker's order, which is the sprite's. `backend/tests/test_avatars.py`
 * holds this list, the server's and the sprite's symbols together.
 */
export const DOODLES = [
  "fox",
  "cat",
  "owl",
  "frog",
  "crab",
  "penguin",
  "fish",
  "bear",
  "ladybug",
  "butterfly",
  "turtle",
  "alien",
  "ghost",
  "robot",
  "rocket",
  "kite",
  "boat",
  "balloon",
  "umbrella",
  "coffee",
  "cactus",
  "mushroom",
  "cloud",
  "flower",
  "donut",
  "icecream",
] as const;

/** Supporter-only to choose (#1476), and after the first list in the sprite. */
export const SUPPORTER_DOODLES = [
  "whale",
  "octopus",
  "hedgehog",
  "dino",
  "unicorn",
  "planet",
  "lighthouse",
  "palette",
  "cupcake",
  "bunny",
] as const;

export type DoodleName = (typeof DOODLES)[number] | (typeof SUPPORTER_DOODLES)[number];

export const DOODLE_SPRITE = "/avatars/doodles.svg";

/** The doodle an avatar URL points at, or null for an uploaded picture or none. */
export function doodleNameOf(url: string | null | undefined): DoodleName | null {
  if (!url || !url.startsWith(`${DOODLE_SPRITE}#`)) return null;
  const name = url.slice(DOODLE_SPRITE.length + 1);
  const known = [...DOODLES, ...SUPPORTER_DOODLES] as readonly string[];
  return known.includes(name) ? (name as DoodleName) : null;
}

/**
 * Whether an avatar URL is a picture somebody uploaded.
 *
 * What decides whether the picture is offered as something to report: a doodle
 * is our drawing, not player-submitted content (R-AVA-09).
 */
export function isUploadedPicture(url: string | null | undefined): boolean {
  return Boolean(url) && doodleNameOf(url) === null;
}

/** What a doodle is called, in the reader's language. */
export function doodleLabel(name: DoodleName): string {
  return ui.avatarDoodles[name];
}
