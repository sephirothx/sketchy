import assert from "node:assert/strict";
import test from "node:test";
import {
  addSharedPromptSelection,
  promptEntriesFromQuickInput,
} from "../src/lib/promptListDrafts.ts";

function toggleWordListSlug(currentSlugs, slugToToggle) {
  if (currentSlugs.includes(slugToToggle)) {
    if (currentSlugs.length <= 1) return currentSlugs;
    return currentSlugs.filter((s) => s !== slugToToggle);
  }
  return [...currentSlugs, slugToToggle];
}

test("prompt list toggling adds new list and removes existing list", () => {
  const initial = ["english_standard"];
  const added = toggleWordListSlug(initial, "english_extended");
  assert.deepEqual(added, ["english_standard", "english_extended"]);

  const removed = toggleWordListSlug(added, "english_standard");
  assert.deepEqual(removed, ["english_extended"]);
});

test("prompt list toggling does not allow deselecting the only selected list", () => {
  const single = ["english_standard"];
  const attemptedRemoval = toggleWordListSlug(single, "english_standard");
  assert.deepEqual(attemptedRemoval, ["english_standard"]);
});

test("quick room prompts become a bounded deduplicated persistence draft", () => {
  assert.deepEqual(promptEntriesFromQuickInput(" apple\nred panda,APPLE\n"), [
    { prompt: "apple", aliases: [] },
    { prompt: "red panda", aliases: [] },
  ]);
});

test("a shared list retains its bearer code and switches incompatible language", () => {
  const selection = addSharedPromptSelection(
    ["english_standard"],
    ["same-code"],
    {
      slug: "user-fr",
      name: "Français",
      description: "",
      language: "fr",
      promptCount: 10,
      isBundled: false,
      version: 1,
    },
    "same-code",
    "en",
  );
  assert.deepEqual(selection.slugs, ["user-fr"]);
  assert.deepEqual(selection.shareCodes, ["same-code"]);
});
