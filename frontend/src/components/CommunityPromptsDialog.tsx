import { useMemo, useRef, useState } from "react";
import { ModalShell } from "./ui/ModalShell";
import {
  findInPrompt,
  groupAlphabetically,
  type PromptMatch,
} from "../lib/communityLists";
import type { CommunityPromptListDetail, PublishedPromptEntry } from "../types";
import { SearchIcon } from "./icons";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/community-lists.css";

type Order = "author" | "alphabetical";

interface Found {
  entry: PublishedPromptEntry;
  match: PromptMatch | null;
}

/** Every prompt in a published list, for when the pane's preview is not enough.

A list can hold 500 prompts, so this is a place to look for one rather than a
longer version of the pane: a search, and two orders. The author's order is
the list as written. A-Z is the list as an index, and only there do the letter
headings appear - in the author's order a letter means nothing.

Search ignores case and accents, in the list's own language, and the prompt it
found is highlighted where the reader sees it (`findInPrompt`). */
export function CommunityPromptsDialog({
  list,
  onClose,
}: {
  list: CommunityPromptListDetail;
  onClose: () => void;
}) {
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");
  const [order, setOrder] = useState<Order>("author");

  // Focus starts in the search: the dialog exists to find something in it.

  const searching = query.trim().length > 0;
  const found = useMemo<Found[]>(() => {
    const all = list.prompts.map((entry) => ({
      entry,
      match: searching ? findInPrompt(entry.prompt, query, list.language) : null,
    }));
    return searching ? all.filter((item) => item.match) : all;
  }, [list, query, searching]);

  const groups = useMemo(
    () => (order === "alphabetical"
      ? groupAlphabetically(found, (item) => item.entry.prompt, list.language)
      : null),
    [found, order, list.language],
  );

  // A cell is a fixed width and a prompt can be 32 characters, so the whole
  // prompt is there on hover when the cell has to cut it.
  const cell = (item: Found) => (
    <li key={item.entry.promptVersionId} className="community-catalogue-prompt" title={item.entry.prompt}>
      {item.match ? <Highlighted text={item.entry.prompt} match={item.match} /> : item.entry.prompt}
    </li>
  );

  return <ModalShell
    title={ui.communityCataloguePage.allPrompts({ count: list.prompts.length })}
    eyebrow={list.name}
    cardClassName="community-prompts-dialog"
    onDismiss={onClose}
    initialFocusRef={searchRef}
  >
    <div className="community-prompts-dialog-tools">
      <label className="community-prompts-search">
        <SearchIcon size={16} />
        <input
          ref={searchRef}
          type="search"
          value={query}
          placeholder={ui.communityCataloguePage.searchPrompts}
          aria-label={ui.communityCataloguePage.searchPrompts}
          maxLength={32}
          onChange={(event) => setQuery(event.target.value)}
        />
        {/* How many of the whole are left, so an empty grid is never a
            question of whether the list is empty or the search is. */}
        {searching && <span className="community-prompts-search-count" aria-live="polite">
          {ui.communityCataloguePage.matchesOfTotal({ matches: found.length, total: list.prompts.length })}
        </span>}
      </label>
      <span className="community-catalogue-sort" role="group" aria-label={ui.communityCataloguePage.order}>
        <button
          type="button"
          aria-pressed={order === "author"}
          onClick={() => setOrder("author")}
        >{ui.communityCataloguePage.authorsOrder}</button>
        <button
          type="button"
          aria-pressed={order === "alphabetical"}
          onClick={() => setOrder("alphabetical")}
        >{ui.communityCataloguePage.alphabetical}</button>
      </span>
    </div>

    <div className="community-prompts-dialog-body">
      {found.length === 0
        ? <p className="community-catalogue-empty">{ui.communityCataloguePage.noPromptMatches({ query: query.trim() })}</p>
        : groups
          ? groups.map((group) => (
              <section key={group.initial} className="community-prompts-group">
                <h3 className="community-prompts-letter">{group.initial}</h3>
                <ul className="community-catalogue-prompts">{group.entries.map(cell)}</ul>
              </section>
            ))
          : <ul className="community-catalogue-prompts">{found.map(cell)}</ul>}
    </div>
  </ModalShell>;
}

/** A prompt with the part the search found marked, cut by code point so an
 * accented letter before the match does not move it. */
function Highlighted({ text, match }: { text: string; match: PromptMatch }) {
  const characters = [...text];
  return <>
    {characters.slice(0, match.start).join("")}
    <mark>{characters.slice(match.start, match.end).join("")}</mark>
    {characters.slice(match.end).join("")}
  </>;
}
