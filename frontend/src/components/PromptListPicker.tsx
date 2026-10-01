import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../lib/api";
import {
  AGNOSTIC_PROMPT_LANGUAGE,
  MIXED_PROMPT_LANGUAGE,
  isPlayableIn,
  promptLanguageLabel,
} from "../lib/promptLanguages";
import { listCommunityPromptLists, listOwnedPromptLists } from "../lib/promptLists";
import {
  MAX_PROMPT_LISTS,
  listsIn,
  promptListTree,
  seriesState,
  toggleSelection,
  type PromptListBranch,
  type PromptListSeries,
  type PromptShelf,
} from "../lib/promptListTree";
import { readEveryPage } from "../lib/communityLists";
import { useAuthStore } from "../store/authStore";
import type { PromptLanguage, PromptListSummary, RoomLanguage } from "../types";
import { AnyLanguageIcon, ChevronRightIcon } from "./icons";
import { FieldHint } from "./RoomSetupControls";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/prompt-lists.css";
import "../styles/lazy/profile.css";

interface PromptListPickerProps {
  /** The room's declared language. Lists answer to it; it is never read back
      off the selection (R-PROMPT-02). */
  language: RoomLanguage;
  /** The language this player plays in, which a mixed-language room shows
      Standard in (#1182). */
  playLanguage?: PromptLanguage;
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  disabled?: boolean;
  /** Reports the loaded lists so the host page can summarize the selection. */
  onListsLoaded?: (lists: PromptListSummary[]) => void;
  /** The catalogue could not be read: nothing will be reported, so a host page
  waiting on the lists to judge a choice has to judge it without them. */
  onListsUnavailable?: () => void;
  /** Lists the host page already knows about — a community list carried in
  from the catalogue. Without them the selection would be reconciled against
  a catalogue that has never heard of the list, and quietly dropped. */
  extraLists?: PromptListSummary[];
}

/** The largest page the community endpoint serves (`MAX_COMMUNITY_PAGE`). */
const STARRED_PAGE_SIZE = 48;
/** A guard against a cursor that never ends: 960 starred lists in one language.
 * The server reads a shortlist whole; reaching this is said on screen. */
const STARRED_MAX_PAGES = 20;

/** Stable identity, so nothing that reports lists back fires on every
render just because it had nothing to report. */
const NO_LISTS: PromptListSummary[] = [];

export function PromptListPicker({
  language,
  playLanguage = "en",
  selectedSlugs,
  onChange,
  disabled = false,
  onListsLoaded,
  onListsUnavailable,
  extraLists = NO_LISTS,
}: PromptListPickerProps) {
  const user = useAuthStore((state) => state.user);
  const userId = user?.id;
  const isAnonymous = user?.isAnonymous;
  const [promptLists, setPromptLists] = useState<PromptListSummary[]>([]);
  // Community lists this account starred: its shortlist, which is what the
  // catalogue's stars are for beyond a public count (R-LIST-16). Tagged with
  // the account it was read for, because a shortlist is personal data: an
  // account signing out here does not unmount the picker, so anything keyed
  // only by "loaded" would stay on screen for whoever holds the browser next.
  const [starred, setStarred] = useState<
    { owner: string; lists: PromptListSummary[]; complete: boolean } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // Which shelves and series the player opened or folded; anything absent
  // follows the selection (`isOpen` below).
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const onListsLoadedRef = useRef(onListsLoaded);
  const onListsUnavailableRef = useRef(onListsUnavailable);

  // Read only while it still belongs to whoever is signed in now. A pending
  // reply for a new account does not keep the old one's shortlist on screen
  // in the meantime, and a request that never answers leaves nothing behind.
  const shortlist =
    starred && !isAnonymous && starred.owner === userId ? starred.lists : NO_LISTS;
  // The guard stopped the read before the shortlist ran out. Said, not hidden:
  // a shortlist that looks whole and is not is the thing reading every page
  // was meant to rule out.
  const shortlistCut = Boolean(
    starred && !isAnonymous && starred.owner === userId && !starred.complete,
  );

  useEffect(() => {
    onListsLoadedRef.current = onListsLoaded;
    onListsUnavailableRef.current = onListsUnavailable;
  }, [onListsLoaded, onListsUnavailable]);

  useEffect(() => {
    onListsLoadedRef.current?.([...promptLists, ...extraLists, ...shortlist]);
  }, [promptLists, extraLists, shortlist]);

  useEffect(() => {
    let cancelled = false;
    async function loadLists() {
      try {
        const bundled = await apiRequest<PromptListSummary[]>("/api/prompt-lists");
        const owned = userId && !isAnonymous
          ? await listOwnedPromptLists().catch(() => [])
          : [];
        if (!cancelled) {
          setPromptLists([...bundled, ...owned]);
        }
      } catch (err) {
        if (!cancelled) {
          setFetchError(refusalText(err, ui.promptListPicker.couldNotLoadPromptLists));
          onListsUnavailableRef.current?.();
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void loadLists();
    return () => {
      cancelled = true;
    };
  }, [userId, isAnonymous]);

  useEffect(() => {
    if (!userId || isAnonymous) return;
    let cancelled = false;
    // Optional: a failure leaves the shortlist out rather than taking the
    // picker down with it.
    // Every page, not the first: a shortlist that stops at a page size loses
    // whatever did not fit, silently, and the server orders it by popularity -
    // so what fell off would be the lists this account starred that few others
    // did. Pages are as large as the server allows, so this is one request for
    // almost every account.
    void readEveryPage(
      (cursor) => listCommunityPromptLists({
        starred: true,
        // A mixed room can play only the lists in no language of these (#1182).
        language: language === MIXED_PROMPT_LANGUAGE ? AGNOSTIC_PROMPT_LANGUAGE : language,
        limit: STARRED_PAGE_SIZE,
        cursor,
      }),
      STARRED_MAX_PAGES,
    )
      .then((read) => {
        if (cancelled) return;
        setStarred({
          owner: userId,
          lists: read.lists.map((list) => ({ ...list, isBundled: false })),
          complete: read.complete,
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [userId, isAnonymous, language]);

  function choose(slugs: readonly string[], on: boolean, branchKey: string) {
    if (disabled) return;
    const next = toggleSelection(selectedSlugs, slugs, on);
    if (next.length !== selectedSlugs.length || next.some((slug, index) => slug !== selectedSlugs[index])) {
      // A shelf opens by itself but never closes by itself: clearing the last
      // list on it would otherwise fold it away under the pointer.
      setOpened((current) => (branchKey in current ? current : { ...current, [branchKey]: true }));
      onChange(next);
    }
  }

  // Everything the picker can offer, so the host page reconciles its
  // selection against the same set the player is looking at.
  const known = [
    ...promptLists,
    ...extraLists.filter((extra) => !promptLists.some((list) => list.slug === extra.slug)),
  ];
  const visibleLists = known.filter((list) => isPlayableIn(list, language, playLanguage));
  const visibleStarred = shortlist.filter(
    (list) => isPlayableIn(list, language, playLanguage)
      && !visibleLists.some((shown) => shown.slug === list.slug),
  );
  const owned = new Set(promptLists.filter((list) => !list.isBundled).map((list) => list.slug));
  const tree = promptListTree({
    official: visibleLists.filter((list) => list.isBundled),
    own: visibleLists.filter((list) => owned.has(list.slug)),
    // A community list carried in from the catalogue's Play: neither the
    // player's nor, necessarily, one they starred.
    carried: visibleLists.filter((list) => !list.isBundled && !owned.has(list.slug)),
    starred: visibleStarred,
  });

  if (loading) {
    return (
      <div className="prompt-list-picker-loading">
        <p className="loading-note" role="status">{ui.promptListPicker.loadingCuratedPromptLists}</p>
      </div>
    );
  }

  if (fetchError && promptLists.length === 0) {
    return (
      <div className="prompt-list-picker-fallback">
        <p className="prompt-list-fallback-note">
          {ui.promptListPicker.choicesUnavailable({ reason: fetchError })}
        </p>
      </div>
    );
  }

  // A shelf opens where something on it is chosen, until the player says
  // otherwise; a series starts folded, saying how much of it is chosen.
  const isOpen = (key: string, fallback: boolean) => opened[key] ?? fallback;
  const flip = (key: string, fallback: boolean) =>
    setOpened((current) => ({ ...current, [key]: !(current[key] ?? fallback) }));

  function branchName(branch: PromptListBranch): string {
    if (branch.kind === "own") return ui.promptListPicker.yourLists;
    if (branch.kind === "carried") return ui.promptListPicker.fromCommunityCatalogue;
    if (branch.kind === "starred") return ui.promptListPicker.listsYouStarred;
    return ui.promptListPicker.shelves[branch.id as PromptShelf] ?? branch.id;
  }

  // One row, for a list on a shelf, in a series or on the player's branches.
  function renderList(list: PromptListSummary, branchKey: string) {
    const isSelected = selectedSlugs.includes(list.slug);
    return (
      <li key={list.slug} className="prompt-list-row">
        <label
          className="prompt-list-check"
          title={list.description || ui.promptListPicker.namePromptCountPrompts({ name: list.name, promptCount: list.promptCount })}
        >
          <input
            type="checkbox"
            checked={isSelected}
            // The last list chosen stays chosen - a room has to draw on
            // something - by `toggleSelection` refusing to clear it, not by
            // disabling it: a disabled box reads as unavailable, not as kept.
            disabled={disabled}
            onChange={(event) => choose([list.slug], event.target.checked, branchKey)}
          />
          <span className="prompt-list-check-name">{list.name}</span>
          {list.language === AGNOSTIC_PROMPT_LANGUAGE && (
            <span className="prompt-list-check-language" title={ui.languagePicker.anyLanguage}>
              <AnyLanguageIcon size={13} />
              <span className="visually-hidden">{ui.languagePicker.anyLanguage}</span>
            </span>
          )}
          <span className="prompt-list-check-count">{ui.format.number({ value: list.promptCount })}</span>
        </label>
        {list.isBundled && <FieldHint
          hint={ui.promptListPicker.howListPlays({ name: list.name })}
          href={`/prompt-lists/${list.slug}`}
        />}
      </li>
    );
  }

  function renderSeries(series: PromptListSeries, branchKey: string) {
    // Not copy: the fold state's key.
    const key = `series:${series.id}`;
    const open = isOpen(key, false);
    const state = seriesState(series, selectedSlugs);
    const slugs = series.lists.map((list) => list.slug);
    const name = ui.promptListPicker.series[series.id] ?? series.id;
    const chosen = series.lists.filter((list) => selectedSlugs.includes(list.slug)).length;
    return (
      <li key={key} className="prompt-list-series">
        <div className="prompt-list-row">
          <button
            type="button"
            className="prompt-list-fold"
            aria-expanded={open}
            aria-controls={`prompt-list-${key}`}
            aria-label={open ? ui.promptListPicker.hideSeries({ name }) : ui.promptListPicker.showSeries({ name })}
            onClick={() => flip(key, false)}
          >
            <ChevronRightIcon size={14} />
          </button>
          <label className="prompt-list-check">
            <SeriesCheckbox
              state={state}
              // Clearing the whole room's selection is refused, as for a list.
              disabled={disabled}
              onChange={(on) => choose(slugs, on, branchKey)}
            />
            <span className="prompt-list-check-name">{name}</span>
            <span className="prompt-list-check-count">
              {ui.promptListPicker.seriesChosen({ chosen, total: series.lists.length })}
            </span>
          </label>
        </div>
        {open && (
          <ul id={`prompt-list-${key}`} className="prompt-list-tree-items is-nested">
            {series.lists.map((list) => renderList(list, branchKey))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <fieldset className="room-choice-group prompt-list-picker-group">
      <legend>{ui.promptListPicker.promptLists}</legend>
      {visibleLists.length === 0 && (
        <p className="prompt-list-fallback-note">
          {ui.promptListPicker.noListsInLanguage({
            language: promptLanguageLabel(language),
          })}
        </p>
      )}
      {selectedSlugs.length > MAX_PROMPT_LISTS && (
        <p className="prompt-list-fallback-note" role="status">
          {ui.promptListPicker.tooManyLists({ max: MAX_PROMPT_LISTS })}
        </p>
      )}
      {tree.length > 0 && <div className="prompt-list-tree">
        {tree.map((branch) => {
          // Not copy: the fold state's key.
          const key = `branch:${branch.id}`;
          const lists = listsIn(branch.items);
          const chosen = lists.filter((list) => selectedSlugs.includes(list.slug)).length;
          const open = isOpen(key, chosen > 0);
          return (
            <section key={key} className="prompt-list-branch">
              <button
                type="button"
                className="prompt-list-branch-toggle"
                aria-expanded={open}
                aria-controls={`prompt-list-${key}`}
                onClick={() => flip(key, chosen > 0)}
              >
                <span className="prompt-list-fold-icon" aria-hidden="true"><ChevronRightIcon size={14} /></span>
                <span className="prompt-list-branch-name">{branchName(branch)}</span>
                {chosen > 0 && (
                  <span className="prompt-list-branch-count">{ui.promptListPicker.chosenCount({ count: chosen })}</span>
                )}
              </button>
              {open && (
                <ul id={`prompt-list-${key}`} className="prompt-list-tree-items">
                  {branch.items.map((item) => (item.kind === "list" ? renderList(item.list, key) : renderSeries(item, key)))}
                </ul>
              )}
            </section>
          );
        })}
      </div>}
      {shortlistCut && <p className="prompt-list-fallback-note">
        {ui.promptListPicker.starredNotAllShown({ shown: shortlist.length })}
      </p>}
    </fieldset>
  );
}

/** A series's checkbox: ticked, clear, or - partly chosen - indeterminate,
which only a property sets, never an attribute. */
function SeriesCheckbox({
  state,
  disabled,
  onChange,
}: {
  state: "none" | "some" | "all";
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={state === "all"}
      disabled={disabled}
      // Partly chosen, a tick chooses the rest.
      onChange={() => onChange(state !== "all")}
    />
  );
}
