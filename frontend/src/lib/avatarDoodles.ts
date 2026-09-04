/**
 * The doodle set a registered player may wear instead of an initial
 * (R-AVA-06): drawings this deployment ships, chosen by name.
 *
 * Each is a symbol in `public/avatars/doodles.svg`, filled with currentColor
 * so the disc's ink paints it and the name color keeps meaning. That sprite
 * is generated: the drawing is `scripts/brand/avatar-doodles.mjs`, inked by
 * `scripts/brand/build-avatar-doodles.mjs`, and editing the sprite by hand is
 * an edit the next build throws away (`scripts/check-doodles-regenerated.sh`).
 *
 * The server holds the same list (`app/auth/avatar_doodles.py`) and a test
 * holds the two and the sprite together. The labels here are the doodles'
 * only names in words, and they are what a screen reader reads. No imports,
 * so this loads anywhere.
 */
export const DOODLE_SPRITE = "/avatars/doodles.svg";

export const DOODLES = [
  "fox",
  "cat",
  "ghost",
  "dog",
  "owl",
  "bear",
  "frog",
  "rabbit",
  "penguin",
  "whale",
  "bee",
  "snail",
  "turtle",
  "robot",
  "alien",
  "mushroom",
  "cactus",
  "rocket",
  "planet",
  "star",
  "cloud",
  "icecream",
  "pencil",
  "palette",
] as const;

export type Doodle = (typeof DOODLES)[number];

/** What a screen reader says for each; the id is not always a word. */
export const DOODLE_LABELS: Record<Doodle, string> = {
  fox: "Fox",
  cat: "Cat",
  ghost: "Ghost",
  dog: "Dog",
  owl: "Owl",
  bear: "Bear",
  frog: "Frog",
  rabbit: "Rabbit",
  penguin: "Penguin",
  whale: "Whale",
  bee: "Bee",
  snail: "Snail",
  turtle: "Turtle",
  robot: "Robot",
  alien: "Alien",
  mushroom: "Mushroom",
  cactus: "Cactus",
  rocket: "Rocket",
  planet: "Planet",
  star: "Star",
  cloud: "Cloud",
  icecream: "Ice cream",
  pencil: "Pencil",
  palette: "Palette",
};

/** Where the server points an identity wearing `name`: into the sprite. */
export function doodleUrl(name: Doodle): string {
  return `${DOODLE_SPRITE}#${name}`;
}

/** The class a disc wears for what fills it, so the stylesheet can tell. */
export function avatarFillClass(url: string | null | undefined): string {
  if (!url) return "";
  return doodleFromUrl(url) ? " has-doodle" : " has-picture";
}

/** The doodle an avatar URL names, or null for an uploaded picture. */
export function doodleFromUrl(url: string | null | undefined): Doodle | null {
  if (!url || !url.startsWith(`${DOODLE_SPRITE}#`)) return null;
  const name = url.slice(DOODLE_SPRITE.length + 1);
  return (DOODLES as readonly string[]).includes(name) ? (name as Doodle) : null;
}
