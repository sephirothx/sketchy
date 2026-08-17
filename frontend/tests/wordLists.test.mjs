import assert from "node:assert/strict";
import test from "node:test";

function toggleWordListSlug(currentSlugs, slugToToggle) {
  if (currentSlugs.includes(slugToToggle)) {
    if (currentSlugs.length <= 1) return currentSlugs;
    return currentSlugs.filter((s) => s !== slugToToggle);
  }
  return [...currentSlugs, slugToToggle];
}

test("word list toggling adds new list and removes existing list", () => {
  const initial = ["english_standard"];
  const added = toggleWordListSlug(initial, "english_extended");
  assert.deepEqual(added, ["english_standard", "english_extended"]);

  const removed = toggleWordListSlug(added, "english_standard");
  assert.deepEqual(removed, ["english_extended"]);
});

test("word list toggling does not allow deselecting the only selected list", () => {
  const single = ["english_standard"];
  const attemptedRemoval = toggleWordListSlug(single, "english_standard");
  assert.deepEqual(attemptedRemoval, ["english_standard"]);
});
