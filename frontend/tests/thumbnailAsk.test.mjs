import assert from "node:assert/strict";
import test from "node:test";

import { droppedFromQueue, newThumbnailAsk, retryIsDue, visibilityFromRecord } from "../src/lib/thumbnailAsk.ts";

test("a card in view asks, and one out of view does not", () => {
  const ask = newThumbnailAsk();
  assert.equal(visibilityFromRecord(ask, true), true);
  assert.equal(visibilityFromRecord(ask, false), false);
});

test("a card dropped while in view does not ask again while it stays in view (#1282 review)", () => {
  // Its fresh observer reports it in view at once; asking then took another
  // waiting card's place, whose drop made it ask at once in turn.
  const ask = newThumbnailAsk();
  droppedFromQueue(ask);
  assert.equal(visibilityFromRecord(ask, true), null);
  assert.equal(visibilityFromRecord(ask, true), null);
});

test("it asks again when it leaves and comes back, and the timer then stands down", () => {
  const ask = newThumbnailAsk();
  droppedFromQueue(ask);
  assert.equal(visibilityFromRecord(ask, false), false);
  assert.equal(visibilityFromRecord(ask, true), true);
  assert.equal(retryIsDue(ask), false, "already asked on the way back in");
});

test("one that never leaves asks again when its timer fires, once", () => {
  const ask = newThumbnailAsk();
  droppedFromQueue(ask);
  assert.equal(retryIsDue(ask), true);
  assert.equal(retryIsDue(ask), false);
  assert.equal(visibilityFromRecord(ask, true), true, "a card that is not waiting asks as any other");
});
