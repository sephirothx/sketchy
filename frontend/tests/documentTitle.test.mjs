import assert from "node:assert/strict";
import test from "node:test";

import { BRAND_TITLE, documentTitle } from "../src/lib/documentTitle.ts";

test("a page's name comes first, the brand after it", () => {
  assert.equal(documentTitle("Gallery"), "Gallery · Sketchy");
  assert.equal(documentTitle("Galerie"), "Galerie · Sketchy");
});

test("a page with no name of its own is the brand alone", () => {
  assert.equal(documentTitle(null), BRAND_TITLE);
  assert.equal(documentTitle(undefined), BRAND_TITLE);
  assert.equal(documentTitle("   "), BRAND_TITLE);
});

test("a room's name is used as it is, trimmed", () => {
  assert.equal(documentTitle("  Doodle den "), "Doodle den · Sketchy");
});

test("the home page says what the game is beside the brand", () => {
  assert.equal(
    documentTitle(null, "Free multiplayer drawing & guessing game"),
    "Sketchy – Free multiplayer drawing & guessing game",
  );
  // A page with a name of its own keeps it: the tagline is the home's.
  assert.equal(documentTitle("Rules", "Free multiplayer drawing & guessing game"), "Rules · Sketchy");
  assert.equal(documentTitle(null, "  "), BRAND_TITLE);
});
