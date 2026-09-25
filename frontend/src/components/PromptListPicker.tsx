import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../lib/api";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { listCommunityPromptLists, listOwnedPromptLists } from "../lib/promptLists";
import { readEveryPage } from "../lib/communityLists";
import { useAuthStore } from "../store/authStore";
import type { PromptLanguage, PromptListSummary } from "../types";
import { CheckIcon, PlusIcon } from "./icons";
import { FieldHint } from "./RoomSetupControls";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/prompt-lists.css";
import "../styles/lazy/profile.css";

interface PromptListPickerProps {
  /** The room's declared language. Lists answer to it; it is never read back
      off the selection (R-PROMPT-02). */
  language: PromptLanguage;
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  disabled?: boolean;
  /** Reports the loaded lists so the host page can summarize the selection. */
  onListsLoaded?: (lists: PromptListSummary[]) => void;
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
  selectedSlugs,
  onChange,
  disabled = false,
  onListsLoaded,
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
  const onListsLoadedRef = useRef(onListsLoaded);

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
  }, [onListsLoaded]);

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
          setFetchError(refusalText(err, ui.promptListPicker.failedLoadPromptLists));
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
        language,
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

  function handleToggle(slug: string) {
    if (disabled) return;
    if (selectedSlugs.includes(slug)) {
      // Don't deselect if it's the only one selected
      if (selectedSlugs.length <= 1) return;
      onChange(selectedSlugs.filter((s) => s !== slug));
    } else {
      onChange([...selectedSlugs, slug]);
    }
  }

  // Everything the picker can offer, so the host page reconciles its
  // selection against the same set the player is looking at.
  const known = [
    ...promptLists,
    ...extraLists.filter((extra) => !promptLists.some((list) => list.slug === extra.slug)),
  ];
  const visibleLists = known.filter((list) => list.language === language);
  const visibleStarred = shortlist.filter(
    (list) => list.language === language && !visibleLists.some((shown) => shown.slug === list.slug),
  );

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

  // One chip, rendered for the catalogue's lists and for the shortlist
  // below it. Extracted rather than duplicated: two copies of this drift.
  function renderChip(wl: PromptListSummary) {
          const isSelected = selectedSlugs.includes(wl.slug);
          const isOnlySelected = isSelected && selectedSlugs.length <= 1;

          return (
            // The toggle and the link are siblings rather than nested: one
            // button inside another is not valid, and a link that selected the
            // list on the way out would be worse than no link.
            <span key={wl.slug} className="prompt-list-chip-group">
              <button
                type="button"
                className="toggle-chip"
                aria-pressed={isSelected}
                disabled={disabled || (isSelected && isOnlySelected)}
                title={wl.description || ui.promptListPicker.namePromptCountPrompts({ name: wl.name, promptCount: wl.promptCount })}
                onClick={() => handleToggle(wl.slug)}
              >
                <span className="toggle-chip-status" aria-hidden="true">
                  {isSelected ? <CheckIcon size={12} /> : <PlusIcon size={12} />}
                </span>
                <span className="toggle-chip-name">{wl.name}</span>
                <span className="prompt-list-chip-count">{wl.promptCount}</span>
              </button>
              {wl.isBundled && <FieldHint
                hint={ui.promptListPicker.howListPlays({ name: wl.name })}
                href={`/prompt-lists/${wl.slug}`}
              />}
            </span>
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
      <div className="toggle-chips" role="group" aria-label={ui.promptListPicker.promptLists}>
        {visibleLists.map(renderChip)}
      </div>
      {visibleStarred.length > 0 && <>
        <p className="prompt-list-starred-label">{ui.promptListPicker.listsYouStarred}</p>
        <div className="toggle-chips" role="group" aria-label={ui.promptListPicker.listsYouStarred}>
          {visibleStarred.map(renderChip)}
        </div>
        {shortlistCut && <p className="prompt-list-fallback-note">
          {ui.promptListPicker.starredNotAllShown({ shown: shortlist.length })}
        </p>}
      </>}
    </fieldset>
  );
}
