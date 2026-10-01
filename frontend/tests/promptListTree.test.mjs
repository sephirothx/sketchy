import assert from "node:assert/strict";
import test from "node:test";
import {
  PROMPT_SHELVES,
  listsIn,
  promptListTree,
  selectionNames,
  seriesState,
  toggleSelection,
} from "../src/lib/promptListTree.ts";

const list = (slug, fields = {}) => ({
  id: slug,
  slug,
  name: fields.name ?? slug,
  description: "",
  language: "en",
  promptCount: 10,
  isBundled: true,
  version: 1,
  shelf: "everyday",
  series: null,
  shelfPosition: 0,
  ...fields,
});

test("official lists stand on their shelves, ordered by position, a series where its first list stands", () => {
  const tree = promptListTree({
    official: [
      list("local", { shelfPosition: 2 }),
      list("gen2", { shelf: "games", series: "pokemon", shelfPosition: 1 }),
      list("standard", { shelfPosition: 0 }),
      list("icons", { shelf: "games", shelfPosition: 0 }),
      list("gen1", { shelf: "games", series: "pokemon", shelfPosition: 0, name: "Generation 1" }),
      list("champions", { shelf: "games", shelfPosition: 5 }),
    ],
    own: [list("mine", { isBundled: false, shelf: null })],
    carried: [],
    starred: [list("board", { isBundled: false, shelf: null })],
  });
  // A shelf this build does not know is kept, after the ones it does.
  assert.deepEqual(tree.map((branch) => branch.id), [...PROMPT_SHELVES, "games", "own", "starred"]);
  assert.deepEqual(tree[0].items.map((item) => item.list.slug), ["standard", "local"]);
  const games = tree[1].items;
  // Icons and the series both stand at 0: the tie goes by name.
  assert.deepEqual(games.map((item) => item.kind === "list" ? item.list.slug : item.id), ["icons", "pokemon", "champions"]);
  assert.deepEqual(games[1].lists.map((entry) => entry.slug), ["gen1", "gen2"]);
  assert.deepEqual(listsIn(games).map((entry) => entry.slug), ["icons", "gen1", "gen2", "champions"]);
});

test("empty branches are left out", () => {
  assert.deepEqual(promptListTree({ official: [], own: [], carried: [], starred: [] }), []);
  const tree = promptListTree({ official: [], own: [], carried: [list("x", { isBundled: false })], starred: [] });
  assert.deepEqual(tree.map((branch) => branch.kind), ["carried"]);
});

test("a series is chosen whole, in part or not at all, and the last list cannot be cleared", () => {
  const series = { kind: "series", id: "pokemon", lists: [list("gen1"), list("gen2")] };
  assert.equal(seriesState(series, []), "none");
  assert.equal(seriesState(series, ["gen1"]), "some");
  assert.equal(seriesState(series, ["gen2", "gen1", "standard"]), "all");

  assert.deepEqual(toggleSelection(["standard"], ["gen1", "gen2"], true), ["standard", "gen1", "gen2"]);
  assert.deepEqual(toggleSelection(["standard", "gen1"], ["gen1", "gen2"], true), ["standard", "gen1", "gen2"]);
  assert.deepEqual(toggleSelection(["standard", "gen1", "gen2"], ["gen1", "gen2"], false), ["standard"]);
  // Clearing everything a room holds keeps it as it was.
  assert.deepEqual(toggleSelection(["gen1", "gen2"], ["gen1", "gen2"], false), ["gen1", "gen2"]);
  assert.deepEqual(toggleSelection(["standard"], ["standard"], false), ["standard"]);
});

test("a summary names a series once", () => {
  const lists = [
    list("standard", { name: "English — Standard" }),
    list("gen1", { series: "pokemon" }),
    list("gen2", { series: "pokemon" }),
    list("gen3", { series: "pokemon" }),
    list("mine", { isBundled: false, shelf: null, name: "Studio in-jokes" }),
  ];
  const label = (series, chosen, total) => `${series} ${chosen}/${total}`;
  assert.deepEqual(
    selectionNames([lists[0], lists[1], lists[2], lists[4]], lists, label),
    ["English — Standard", "pokemon 2/3", "Studio in-jokes"],
  );
});
