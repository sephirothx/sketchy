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
