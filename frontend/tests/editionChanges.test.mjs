import assert from "node:assert/strict";
import test from "node:test";
import {
  describeEditionChanges,
  editionChanges,
  publishedEditionStatus,
} from "../src/lib/promptListDrafts.ts";

const live = {
  name: "Seaside",
  description: "",
  tags: ["nature"],
  prompts: [
    { conceptId: "a", prompt: "gull" },
    { conceptId: "b", prompt: "lighthouse" },
  ],
};

test("a reworded prompt is one change, matched by concept", () => {
  const changes = editionChanges(live, {
    ...live,
    prompts: [{ conceptId: "a", prompt: "seagull" }, { conceptId: "c", prompt: "crab" }],
  });
  assert.deepEqual(changes.added, ["crab"]);
  assert.deepEqual(changes.removed, ["lighthouse"]);
  assert.deepEqual(changes.reworded, [{ from: "gull", to: "seagull" }]);
  assert.equal(changes.name || changes.description || changes.tags, false);
});

test("metadata changes are said, and a reorder alone says nothing", () => {
  const reordered = editionChanges(live, { ...live, prompts: [...live.prompts].reverse() });
  assert.deepEqual(describeEditionChanges(reordered), []);

  const renamed = editionChanges(live, { ...live, name: "Coast", tags: ["places"] });
  assert.equal(describeEditionChanges(renamed).length, 2);
});

test("the status follows the pending edition first, then the changes", () => {
  const base = { visibility: "public", liveEdition: { number: 1 }, pendingEdition: null, unpublishedChanges: false };
  assert.equal(publishedEditionStatus(null), "none");
  assert.equal(publishedEditionStatus({ ...base, visibility: "private" }), "none");
  assert.equal(publishedEditionStatus(base), "live");
  assert.equal(publishedEditionStatus({ ...base, unpublishedChanges: true }), "changed");
  assert.equal(
    publishedEditionStatus({ ...base, pendingEdition: { number: 2 } }),
    "update-under-review",
  );
  assert.equal(
    publishedEditionStatus({ ...base, liveEdition: null, pendingEdition: { number: 1 } }),
    "first-under-review",
  );
});

test("a word removed and typed in again is no change to a player", () => {
  const changes = editionChanges(live, {
    ...live,
    prompts: [{ conceptId: "a", prompt: "gull" }, { conceptId: "z", prompt: "lighthouse" }],
  });
  assert.deepEqual(changes.added, []);
  assert.deepEqual(changes.removed, []);
});

test("a long change names a few and counts the rest", () => {
  const many = Array.from({ length: 20 }, (_, index) => ({ conceptId: `n${index}`, prompt: `word${index}` }));
  const [line] = describeEditionChanges(editionChanges({ ...live, prompts: [] }, { ...live, prompts: many }));
  assert.match(line, /word7 and 12 more/);
  assert.doesNotMatch(line, /word8/);
});

test("edits after an update was sent for review are said, not hidden", () => {
  const waiting = { visibility: "public", liveEdition: { number: 1 }, pendingEdition: { number: 2 }, unpublishedChanges: true };
  assert.equal(publishedEditionStatus(waiting), "changed-since-review");
  assert.equal(publishedEditionStatus({ ...waiting, liveEdition: null }), "changed-since-review");
});
