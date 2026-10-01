import type { PromptListSummary } from "../types";

/**
 * The shelves official lists stand on, in the order the picker shows them
 * (#1374, R-PROMPT-14). The server's `prompt_content.PROMPT_SHELVES`, mirrored
 * here because the shelf's name is player copy and lives in the catalogue;
 * `backend/tests/test_wire_contract.py` holds the two to the same slugs in the
 * same order.
 */
export const PROMPT_SHELVES = ["everyday"] as const;

export type PromptShelf = (typeof PROMPT_SHELVES)[number];

/** One list, as a row the player ticks. */
export interface PromptListLeaf {
  kind: "list";
  list: PromptListSummary;
}

/** Official lists grouped under one name on a shelf - a franchise's
generations, say - picked one by one or all at once (GLOSSARY *Series*). */
export interface PromptListSeries {
  kind: "series";
  id: string;
  lists: PromptListSummary[];
}

export type PromptListTreeItem = PromptListLeaf | PromptListSeries;

/** A heading of the tree: an official shelf, or one of the player's own
branches - their lists, the community lists they starred, and a community
list carried in from the catalogue that is neither. */
export interface PromptListBranch {
  id: string;
  kind: "shelf" | "own" | "carried" | "starred";
  items: PromptListTreeItem[];
}

/** Where a list sorts on its shelf: its own position, or a series's first. */
function position(item: PromptListTreeItem): number {
  if (item.kind === "list") return item.list.shelfPosition ?? 0;
  return Math.min(...item.lists.map((list) => list.shelfPosition ?? 0));
}

/**
 * The picker's tree over the lists it may offer.
 *
 * Official lists stand on their shelves in `PROMPT_SHELVES` order, a series
 * where its first list stands, each shelf ordered by position and then by
 * name. A shelf this build does not know is kept, after the known ones, rather
 * than dropping its lists. The player's own lists, a carried community list
 * and the starred ones follow in the order they arrived. Empty branches are
 * left out.
 */
export function promptListTree({
  official,
  own,
  carried,
  starred,
}: {
  official: PromptListSummary[];
  own: PromptListSummary[];
  carried: PromptListSummary[];
  starred: PromptListSummary[];
}): PromptListBranch[] {
  const shelves = new Map<string, PromptListSummary[]>();
  for (const list of official) {
    const shelf = list.shelf ?? PROMPT_SHELVES[0];
    shelves.set(shelf, [...(shelves.get(shelf) ?? []), list]);
  }
  const known: readonly string[] = PROMPT_SHELVES;
  const order = [
    ...PROMPT_SHELVES.filter((shelf) => shelves.has(shelf)),
    ...[...shelves.keys()].filter((shelf) => !known.includes(shelf)).sort(),
  ];
  const branches: PromptListBranch[] = order.map((shelf) => {
    const items: PromptListTreeItem[] = [];
    const series = new Map<string, PromptListSeries>();
    for (const list of shelves.get(shelf) ?? []) {
      if (!list.series) {
        items.push({ kind: "list", list });
        continue;
      }
      let group = series.get(list.series);
      if (!group) {
        group = { kind: "series", id: list.series, lists: [] };
        series.set(list.series, group);
        items.push(group);
      }
      group.lists.push(list);
    }
    for (const group of series.values()) {
      group.lists.sort((left, right) =>
        (left.shelfPosition ?? 0) - (right.shelfPosition ?? 0)
        || left.name.localeCompare(right.name));
    }
    items.sort((left, right) => position(left) - position(right)
      || nameOf(left).localeCompare(nameOf(right)));
    return { id: shelf, kind: "shelf", items };
  });
  const asLeaves = (lists: PromptListSummary[]): PromptListTreeItem[] =>
    lists.map((list) => ({ kind: "list", list }));
  if (own.length) branches.push({ id: "own", kind: "own", items: asLeaves(own) });
  if (carried.length) branches.push({ id: "carried", kind: "carried", items: asLeaves(carried) });
  if (starred.length) branches.push({ id: "starred", kind: "starred", items: asLeaves(starred) });
  return branches;
}

function nameOf(item: PromptListTreeItem): string {
  return item.kind === "list" ? item.list.name : item.id;
}

/** Every list under a branch or item, series opened up. */
export function listsIn(items: PromptListTreeItem[]): PromptListSummary[] {
  return items.flatMap((item) => (item.kind === "list" ? [item.list] : item.lists));
}

/** How much of a series is chosen: none, some or every list in it. */
export function seriesState(
  series: PromptListSeries,
  selected: readonly string[],
): "none" | "some" | "all" {
  const chosen = series.lists.filter((list) => selected.includes(list.slug)).length;
  if (chosen === 0) return "none";
  return chosen === series.lists.length ? "all" : "some";
}

/**
 * The selection after ticking or clearing `slugs` together - one list, or a
 * whole series. Clearing never leaves the room with nothing: a selection that
 * would empty keeps what it had, as a single chip always refused to clear.
 */
export function toggleSelection(
  selected: readonly string[],
  slugs: readonly string[],
  on: boolean,
): string[] {
  if (on) return [...selected, ...slugs.filter((slug) => !selected.includes(slug))];
  const kept = selected.filter((slug) => !slugs.includes(slug));
  return kept.length > 0 ? kept : [...selected];
}

/**
 * The selection's names for a one-line summary: each list by its name, and a
 * series once, by `seriesLabel` - nine generations are one thing to a host.
 * `lists` is everything loaded, so a series knows how many it holds.
 */
export function selectionNames(
  selected: readonly PromptListSummary[],
  lists: readonly PromptListSummary[],
  seriesLabel: (series: string, chosen: number, total: number) => string,
): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  for (const list of selected) {
    if (!list.series || !list.isBundled) {
      names.push(list.name);
      continue;
    }
    if (seen.has(list.series)) continue;
    seen.add(list.series);
    const members = lists.filter((other) => other.isBundled && other.series === list.series
      && other.language === list.language);
    const chosen = selected.filter((other) => members.includes(other)).length;
    names.push(seriesLabel(list.series, chosen, members.length));
  }
  return names;
}
