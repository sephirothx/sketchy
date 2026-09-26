import assert from "node:assert/strict";
import test from "node:test";
import { duplicateName, emailPublishBlocker, promptEntriesFromQuickInput } from "../src/lib/promptListDrafts.ts";
import {
  availablePromptLanguages,
  promptLanguageEndonym,
  promptLanguageLabel,
  gameEndSpelledForSeat,
  spelledForSeat,
  isPlayableIn,
  preferredPromptLanguage,
  reconcileSelectionForLanguage,
  selectionForLanguage,
  sortRoomsByLanguage,
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

test("the browser says which language a visitor plays in, English if it cannot", () => {
  assert.equal(preferredPromptLanguage(["de-CH", "de", "en"]), "de");
  assert.equal(preferredPromptLanguage(["pt-BR"]), "pt");
  assert.equal(preferredPromptLanguage(["ja", "zh-CN", "fr"]), "fr");
  assert.equal(preferredPromptLanguage(["ja", "zh-CN"]), "en");
  assert.equal(preferredPromptLanguage([]), "en");
  assert.equal(preferredPromptLanguage(undefined), "en");
});

test("the lobby leads with your language and hides nobody", () => {
  const rooms = [
    { code: "A", promptLanguage: "en" },
    { code: "B", promptLanguage: "de" },
    { code: "C", promptLanguage: "fr" },
    { code: "D", promptLanguage: "de" },
  ];
  assert.deepEqual(
    sortRoomsByLanguage(rooms, "de").map((room) => room.code),
    ["B", "D", "A", "C"],
  );
  // Stable within each group: the server's order survives.
  assert.deepEqual(
    sortRoomsByLanguage(rooms, "it").map((room) => room.code),
    ["A", "B", "C", "D"],
  );
  assert.equal(sortRoomsByLanguage(rooms, "de").length, rooms.length);
});

test("a selection that is not in the room's language is replaced, not kept", () => {
  const lists = [
    { slug: "english_standard", language: "en" },
    { slug: "english_extended", language: "en" },
    { slug: "german_standard", language: "de" },
    { slug: "german_extended", language: "de" },
  ];
  // What a German player used to submit: their language, England's list.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "de", ["english_standard"]),
    ["german_standard"],
  );
  // Anything already in the language is left exactly as it is.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "de", ["german_extended"]),
    ["german_extended"],
  );
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "en", ["english_extended", "english_standard"]),
    ["english_extended", "english_standard"],
  );
  // A half-right selection keeps its right half rather than resetting.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "de", ["english_standard", "german_extended"]),
    ["german_extended"],
  );
  // And a language with nothing to offer says so, rather than borrowing.
  assert.deepEqual(reconcileSelectionForLanguage(lists, "it", ["english_standard"]), []);
});

test("a list in no language is played in every room and follows it across a switch", () => {
  const lists = [
    { slug: "english_standard", language: "en" },
    { slug: "german_standard", language: "de" },
    { slug: "pokemon", language: "zxx" },
  ];
  assert.equal(isPlayableIn(lists[2], "de"), true);
  assert.equal(isPlayableIn(lists[0], "de"), false);
  // Not a language a room can be opened in.
  assert.deepEqual(availablePromptLanguages(lists, "en"), ["de", "en"]);
  // Kept beside the room's own lists when they are reconciled...
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "de", ["english_standard", "pokemon"]),
    ["pokemon"],
  );
  // ...and carried when the host switches the room's language, beside the new
  // language's Standard list rather than instead of it.
  assert.deepEqual(
    selectionForLanguage(lists, "de", ["english_standard", "pokemon"]),
    ["german_standard", "pokemon"],
  );
  assert.deepEqual(selectionForLanguage(lists, "de"), ["german_standard"]);
});

test("a mixed room plays Standard, once, and lists in no language", () => {
  const languages = ["de", "en", "es", "fr", "it", "nl", "pt"];
  const standard = languages.map((language) => ({
    slug: `${{ de: "german", en: "english", es: "spanish", fr: "french", it: "italian", nl: "dutch", pt: "portuguese" }[language]}_standard`,
    language,
    isBundled: true,
  }));
  const lists = [
    ...standard,
    { slug: "german_extended", language: "de", isBundled: true },
    { slug: "mine", language: "de", isBundled: false },
    // A player's own list named like Standard is not Standard.
    { slug: "fake_standard", language: "de", isBundled: false },
    { slug: "pokemon", language: "zxx", isBundled: false },
  ];
  // Offered once Standard is there in every language, and last.
  assert.equal(availablePromptLanguages(lists, "de").at(-1), "mul");
  assert.equal(availablePromptLanguages(lists.slice(1), "de").includes("mul"), false);
  // Standard shown in the language the player plays, beside lists in none.
  const playable = lists.filter((list) => isPlayableIn(list, "mul", "de")).map((l) => l.slug);
  assert.deepEqual(playable, ["german_standard", "pokemon"]);
  assert.deepEqual(
    selectionForLanguage(lists, "mul", ["german_extended", "pokemon"], "fr"),
    ["french_standard", "pokemon"],
  );
  // Another host's Standard is shown in this player's language instead.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "mul", ["english_standard"], "de"),
    ["german_standard"],
  );
  // A room already mixed keeps saying so while its lists load.
  assert.equal(availablePromptLanguages([], "mul").includes("mul"), true);
  assert.equal(promptLanguageLabel("mul"), "Mixed");
  assert.equal(promptLanguageEndonym("mul"), "Mixed");
});

test("a room-wide prompt is read in the seat's own language", () => {
  const ended = { prompt: "bow tie", prompts: { de: "Fliege", fr: "nœud papillon" } };
  assert.equal(spelledForSeat(ended, "de").prompt, "Fliege");
  assert.equal(spelledForSeat(ended, "it").prompt, "bow tie");
  assert.equal(spelledForSeat({ prompt: "dog" }, "de").prompt, "dog");
  const game = gameEndSpelledForSeat(
    {
      scores: [],
      drawings: [{ prompt: "bow tie", prompts: { de: "Fliege" } }],
      highlights: [
        { kind: "hardest_prompt", prompt: "bow tie", prompts: { de: "Fliege" } },
        { kind: "best_drawer", guessRatio: 1 },
      ],
    },
    "de",
  );
  assert.equal(game.drawings[0].prompt, "Fliege");
  assert.equal(game.highlights[0].prompt, "Fliege");
  assert.deepEqual(game.highlights[1], { kind: "best_drawer", guessRatio: 1 });
});

test("the lobby leads with your language, then mixed rooms", () => {
  const rooms = [
    { id: "it", promptLanguage: "it" },
    { id: "mul", promptLanguage: "mul" },
    { id: "de", promptLanguage: "de" },
  ];
  assert.deepEqual(sortRoomsByLanguage(rooms, "de").map((room) => room.id), ["de", "mul", "it"]);
});

test("a duplicate's name fits the server's 64 characters without splitting one", () => {
  assert.equal(duplicateName("Kitchen things"), "Kitchen things (duplicate)");
  // An odd number of code units before the emoji puts a UTF-16 cut in the
  // middle of one; the server counts code points, so an emoji is one of 64.
  const name = `a${"🦦".repeat(63)}`;
  const shortened = duplicateName(name);
  assert.ok(shortened.isWellFormed(), "no lone surrogate");
  assert.equal(Array.from(shortened).length, 64);
  assert.ok(shortened.endsWith(" (duplicate)"));
  assert.equal(shortened, `a${"🦦".repeat(51)} (duplicate)`);
});

test("the Publish panel names what the email state is keeping it from", () => {
  const state = (over) => ({
    address: null, verified: false, pendingAddress: null, reminderDue: false, deliveryConfigured: true, ...over,
  });
  assert.equal(emailPublishBlocker(null, false), null, "not read yet is not a refusal");
  assert.equal(emailPublishBlocker(state({ address: "a@b.test", verified: true }), false), null);
  assert.equal(emailPublishBlocker(state({}), true), null, "a published list can always be unpublished");
  assert.equal(emailPublishBlocker(state({}), false), "no-address");
  assert.equal(emailPublishBlocker(state({ pendingAddress: "a@b.test" }), false), "pending");
  assert.equal(emailPublishBlocker(state({ deliveryConfigured: false }), false), "undeliverable");
  // Submitted on a server without mail: nothing was sent, so nothing to confirm.
  assert.equal(
    emailPublishBlocker(state({ pendingAddress: "a@b.test", deliveryConfigured: false }), false),
    "undeliverable",
  );
});
