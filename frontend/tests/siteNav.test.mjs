import assert from "node:assert/strict";
import test from "node:test";

import { siteLinkCurrent } from "../src/lib/siteNav.ts";

test("a site link is the current page only on its own path", () => {
  assert.equal(siteLinkCurrent("/", "/"), "page");
  assert.equal(siteLinkCurrent("/gallery", "/gallery"), "page");
  assert.equal(siteLinkCurrent("/rules", "/rules/"), "page");
  assert.equal(siteLinkCurrent("/gallery", "/rules"), undefined);
});

test("a page nested under a link marks the section, not the page", () => {
  assert.equal(siteLinkCurrent("/gallery", "/gallery/42"), "true");
  assert.equal(siteLinkCurrent("/prompt-lists", "/prompt-lists/en-standard"), "true");
  assert.equal(siteLinkCurrent("/community-lists", "/community-lists/7"), "true");
});

test("the lobby is never current off the lobby, and prefixes are whole segments", () => {
  assert.equal(siteLinkCurrent("/", "/gallery"), undefined);
  assert.equal(siteLinkCurrent("/", "/profile/3"), undefined);
  // My prompt lists is not under Prompt stats, and a lookalike path is not under the Gallery.
  assert.equal(siteLinkCurrent("/prompt-lists", "/my-prompt-lists"), undefined);
  assert.equal(siteLinkCurrent("/gallery", "/gallery-old"), undefined);
});
