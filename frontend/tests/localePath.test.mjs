import assert from "node:assert/strict";
import test from "node:test";

import { isPublicPath, localePath, splitLocalePath } from "../src/lib/localePath.ts";

test("a public page's address names its language; English has none", () => {
  assert.deepEqual(splitLocalePath("/de/rules"), { locale: "de", path: "/rules" });
  assert.deepEqual(splitLocalePath("/fr"), { locale: "fr", path: "/" });
  assert.deepEqual(splitLocalePath("/fr/"), { locale: "fr", path: "/" });
  assert.deepEqual(splitLocalePath("/PT/prompt-lists/x"), { locale: "pt", path: "/prompt-lists/x" });
  assert.deepEqual(splitLocalePath("/rules"), { locale: null, path: "/rules" });
  // An overlay's background carries the page's query (review of #1462).
  assert.deepEqual(splitLocalePath("/de/prompt-lists?sort=easiest"), { locale: "de", path: "/prompt-lists?sort=easiest" });
  assert.deepEqual(splitLocalePath("/de?x=1#top"), { locale: "de", path: "/?x=1#top" });
  // English is the unprefixed address, not a second one.
  assert.deepEqual(splitLocalePath("/en/rules"), { locale: null, path: "/en/rules" });
});

test("only a public page has an address per language", () => {
  assert.deepEqual(splitLocalePath("/de/room/ABC123"), { locale: null, path: "/de/room/ABC123" });
  assert.deepEqual(splitLocalePath("/de/settings"), { locale: null, path: "/de/settings" });
  assert.deepEqual(splitLocalePath("/xx/rules"), { locale: null, path: "/xx/rules" });
  assert.equal(localePath("/room/ABC123", "de"), "/room/ABC123");
  assert.equal(localePath("/community-lists", "de"), "/community-lists");
});

test("a path is put in a language, and English stays as it is", () => {
  assert.equal(localePath("/", "de"), "/de");
  assert.equal(localePath("/terms", "it"), "/it/terms");
  assert.equal(localePath("/prompt-lists/english_standard?sort=easiest", "nl"), "/nl/prompt-lists/english_standard?sort=easiest");
  assert.equal(localePath("/rules", "en"), "/rules");
  assert.equal(localePath("/rules", null), "/rules");
});

test("the public pages are the indexable routes", () => {
  for (const path of ["/", "/rules", "/terms", "/privacy", "/solo", "/prompt-lists", "/prompt-lists/x"]) {
    assert.ok(isPublicPath(path), path);
  }
  for (const path of ["/create", "/gallery", "/community-lists", "/prompt-lists/x/y", "/profile"]) {
    assert.ok(!isPublicPath(path), path);
  }
});
