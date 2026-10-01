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
  selectionInPlayLanguage,
  selectionForLanguage,
  rankedPromptLanguages,
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
  assert.equal(preferredPromptLanguage(["pl-PL"]), "pl");
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

test("a mixed room plays Standard and Extended, once, and lists in no language", () => {
  const languages = ["de", "en", "es", "fr", "it", "nl", "pl", "pt"];
  const stems = { de: "german", en: "english", es: "spanish", fr: "french", it: "italian", nl: "dutch", pl: "polish", pt: "portuguese" };
  // The server names each list's family (#1374); the client reads that, not
  // the slug.
  const standard = languages.map((language) => ({
    slug: `${stems[language]}_standard`,
    language,
    isBundled: true,
    family: "english_standard",
  }));
  const extended = languages.map((language) => ({
    slug: `${stems[language]}_extended`,
    language,
    isBundled: true,
    family: "english_extended",
  }));
  const lists = [
    ...standard,
    ...extended,
    // Local is its own language's alone, so a mixed room cannot play it.
    { slug: "german_local", language: "de", isBundled: true },
    { slug: "mine", language: "de", isBundled: false },
    // A player's own list named like Standard is not Standard.
    { slug: "fake_standard", language: "de", isBundled: false },
    { slug: "fake_extended", language: "de", isBundled: false },
    { slug: "pokemon", language: "zxx", isBundled: false },
  ];
  // Offered once Standard is there in every language, and last.
  assert.equal(availablePromptLanguages(lists, "de").at(-1), "mul");
  assert.equal(availablePromptLanguages(lists.slice(1), "de").includes("mul"), false);
  // Standard and Extended shown in the language the player plays, beside
  // lists in none.
  const playable = lists.filter((list) => isPlayableIn(list, "mul", "de")).map((l) => l.slug);
  assert.deepEqual(playable, ["german_standard", "german_extended", "pokemon"]);
  assert.deepEqual(
    selectionForLanguage(lists, "mul", ["german_local", "pokemon"], "fr"),
    ["french_standard", "pokemon"],
  );
  // Extended is the same list in every language, so it follows the room into
  // Mixed - shown in the host's language - and out of it again; Local stays
  // behind, and so does a player's own list that merely sounds like Extended.
  assert.deepEqual(
    selectionForLanguage(lists, "mul", ["german_standard", "german_extended", "german_local"], "fr"),
    ["french_standard", "french_extended"],
  );
  assert.deepEqual(
    selectionForLanguage(lists, "mul", ["fake_extended"], "fr"),
    ["french_standard"],
  );
  assert.deepEqual(
    selectionForLanguage(lists, "de", ["french_standard", "french_extended"], "fr"),
    ["german_standard", "german_extended"],
  );
  // Another host's Standard and Extended are shown in this player's language.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "mul", ["english_standard"], "de"),
    ["german_standard"],
  );
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "mul", ["english_standard", "english_extended", "pokemon"], "de"),
    ["german_standard", "german_extended", "pokemon"],
  );
  // The editor maps a saved room's lists into this host's copies without
  // dropping or adding anything.
  assert.deepEqual(
    selectionInPlayLanguage(lists, "mul", ["english_standard", "english_extended", "pokemon"], "de"),
    ["german_standard", "german_extended", "pokemon"],
  );
  assert.deepEqual(
    selectionInPlayLanguage(lists, "de", ["german_local"], "fr"),
    ["german_local"],
  );
  // Local does not follow the room into Mixed.
  assert.deepEqual(
    reconcileSelectionForLanguage(lists, "mul", ["german_local"], "de"),
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

test("then the other languages you play in, in your order, then the rest (#1211)", () => {
  const rooms = [
    { id: "fr", promptLanguage: "fr" },
    { id: "es", promptLanguage: "es" },
    { id: "nl", promptLanguage: "nl" },
    { id: "mul", promptLanguage: "mul" },
    { id: "it", promptLanguage: "it" },
    { id: "es2", promptLanguage: "es" },
  ];
  assert.deepEqual(
    sortRoomsByLanguage(rooms, "it", ["nl", "es"]).map((room) => room.id),
    ["it", "mul", "nl", "es", "es2", "fr"],
  );
  // Nothing ranked twice, nothing hidden: the default listed again stays first.
  assert.deepEqual(
    sortRoomsByLanguage(rooms, "it", ["it", "es"]).map((room) => room.id),
    ["it", "mul", "es", "es2", "fr", "nl"],
  );
});

test("a picker lists your languages first, in your order, and all eight", () => {
  const ranked = rankedPromptLanguages("it", ["nl", "es"]);
  assert.deepEqual(ranked.slice(0, 3), ["it", "nl", "es"]);
  assert.equal(ranked.length, 8);
  assert.equal(new Set(ranked).size, 8);
  // Within what a form can offer: a language it cannot is left out, not added.
  assert.deepEqual(rankedPromptLanguages("it", ["nl"], ["en", "nl"]), ["nl", "en"]);
});

test("a themed official family follows the room across languages and into Mixed", () => {
  // Not Standard or Extended by name: the family the server reports is what
  // makes a list one list in every language (#1374).
  const languages = ["de", "en", "es", "fr", "it", "nl", "pl", "pt"];
  const lists = [
    ...languages.map((language) => ({ slug: `standard_${language}`, language, isBundled: true, family: "standard_en" })),
    ...languages.map((language) => ({ slug: `critters_${language}`, language, isBundled: true, family: "critters_en" })),
    { slug: "english_standard", language: "en", isBundled: true, family: "standard_en" },
    { slug: "german_local", language: "de", isBundled: true, family: null },
  ];
  const playable = lists.filter((list) => isPlayableIn(list, "mul", "fr")).map((list) => list.slug);
  assert.deepEqual(playable, ["standard_fr", "critters_fr"]);
  assert.equal(isPlayableIn(lists.at(-1), "mul", "de"), false);
  assert.deepEqual(
    selectionForLanguage(lists, "it", ["standard_de", "critters_de", "german_local"]),
    ["standard_it", "critters_it"],
  );
  assert.deepEqual(
    selectionInPlayLanguage(lists, "mul", ["critters_en"], "pl"),
    ["critters_pl"],
  );
});
