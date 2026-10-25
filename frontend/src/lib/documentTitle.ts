/**
 * What the browser tab says.
 *
 * Every tab used to read "Sketchy", whatever page it held, so three open tabs
 * - a room, the Gallery, Rules - were three identical labels. The page's own
 * name comes first because a narrow tab shows only its first few letters,
 * and the brand after it, which is what a history list or a bookmark needs.
 * The page's name is the caller's, from the catalogue or the room; only the
 * brand is fixed here, because no language translates it.
 */

// Not copy: the product's name, the one word no language translates.
export const BRAND_TITLE = "Sketchy";

/** "Gallery · Sketchy", or the brand alone for a page with no name of its own.

The home page has no name of its own but says what the game is beside the
brand - "Sketchy – Free multiplayer drawing & guessing game" - because that
title is what a search result shows (#1459), and the server writes the same
words into the page it serves. */
export function documentTitle(page?: string | null, tagline?: string): string {
  const name = page?.trim();
  if (name) return `${name} · ${BRAND_TITLE}`;
  const line = tagline?.trim();
  return line ? `${BRAND_TITLE} – ${line}` : BRAND_TITLE;
}
