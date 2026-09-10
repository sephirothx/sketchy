import assert from "node:assert/strict";
import test from "node:test";
import {
  addSharedPromptSelection,
  promptEntriesFromQuickInput,
} from "../src/lib/promptListDrafts.ts";
import {
  availablePromptLanguages,
  selectionForLanguage,
} from "../src/lib/promptLanguages.ts";

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

const sharedFrenchList = {
  slug: "user-fr",
  name: "Français",
  description: "",
  language: "fr",
  promptCount: 10,
  isBundled: false,
  version: 1,
};

test("a shared list in the room's language is added and keeps its bearer code", () => {
  const selection = addSharedPromptSelection(
    ["francais_standard"],
    [],
    sharedFrenchList,
    "same-code",
    "fr",
  );
  assert.equal(selection.ok, true);
  assert.deepEqual(selection.slugs, ["francais_standard", "user-fr"]);
  assert.deepEqual(selection.shareCodes, ["same-code"]);
});

test("a shared list in another language is refused, not swapped in", () => {
  const selection = addSharedPromptSelection(
    ["english_standard"],
    ["same-code"],
    sharedFrenchList,
    "another-code",
    "en",
  );
  assert.deepEqual(selection, { ok: false, language: "fr" });
});

test("the language options offered are the ones with content, plus the room's own", () => {
  const lists = [
    { slug: "english_standard", language: "en" },
    { slug: "english_extended", language: "en" },
    { slug: "user-de", language: "de" },
  ];
  // Sorted by the name each language uses for itself, which is what the
  // picker shows: "Deutsch" comes before "English".
  assert.deepEqual(availablePromptLanguages(lists, "en"), ["de", "en"]);
  assert.deepEqual(availablePromptLanguages([], "fr"), ["fr"]);
  assert.deepEqual(selectionForLanguage(lists, "de"), ["user-de"]);
  assert.deepEqual(selectionForLanguage(lists, "it"), []);
  // Standard rather than whatever sorts first: the catalogue is alphabetical,
  // so the first German list is `german_extended`.
  assert.deepEqual(
    selectionForLanguage(
      [
        { slug: "german_extended", language: "de" },
        { slug: "german_standard", language: "de" },
      ],
      "de",
    ),
    ["german_standard"],
  );
});
