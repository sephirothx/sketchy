import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiRequest } from "../lib/api";
import { promptLanguageLabel } from "../lib/promptLanguages";
import {
  listCommunityPromptLists,
  listOwnedPromptLists,
  resolveSharedPromptList,
} from "../lib/promptLists";
import { addSharedPromptSelection } from "../lib/promptListDrafts";
import { useAuthStore } from "../store/authStore";
import type { PromptLanguage, PromptListSummary, SharedPromptList } from "../types";
import { PromptContentReportDialog } from "./PromptContentReportDialog";
import { AlertIcon, CheckIcon, InfoIcon, PlusIcon } from "./icons";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

interface PromptListPickerProps {
  /** The room's declared language. Lists answer to it; it is never read back
      off the selection (R-PROMPT-02). */
  language: PromptLanguage;
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  shareCodes?: string[];
  onShareCodesChange?: (codes: string[]) => void;
  disabled?: boolean;
  /** Reports the loaded lists so the host page can summarize the selection. */
  onListsLoaded?: (lists: PromptListSummary[]) => void;
  /** Lists the host page already knows about — a community list carried in
  from the catalogue. Without them the selection would be reconciled against
  a catalogue that has never heard of the list, and quietly dropped. */
  extraLists?: PromptListSummary[];
}

/** Stable identity, so nothing that reports lists back fires on every
render just because it had nothing to report. */
const NO_LISTS: PromptListSummary[] = [];

export function PromptListPicker({
  language,
  selectedSlugs,
  onChange,
  shareCodes = [],
  onShareCodesChange,
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
    { owner: string; lists: PromptListSummary[] } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [shareCode, setShareCode] = useState("");
  const [shareError, setShareError] = useState<string | null>(null);
  const [resolvingShare, setResolvingShare] = useState(false);
  const [sharedAccess, setSharedAccess] = useState<Record<string, { code: string; list: SharedPromptList }>>({});
  const [reportingSlug, setReportingSlug] = useState<string | null>(null);
  const [reportNotice, setReportNotice] = useState<string | null>(null);
  const onListsLoadedRef = useRef(onListsLoaded);

  // Read only while it still belongs to whoever is signed in now. A pending
  // reply for a new account does not keep the old one's shortlist on screen
  // in the meantime, and a request that never answers leaves nothing behind.
  const shortlist =
    starred && !isAnonymous && starred.owner === userId ? starred.lists : NO_LISTS;

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
    void listCommunityPromptLists({ starred: true, language, limit: 24 })
      .then((page) => {
        if (cancelled) return;
        setStarred({
          owner: userId,
          lists: page.lists.map((list) => ({ ...list, isBundled: false })),
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [userId, isAnonymous, language]);

  async function addSharedList(event: FormEvent) {
    event.preventDefault();
    if (disabled || resolvingShare || !shareCode.trim()) return;
    setResolvingShare(true);
    setShareError(null);
    try {
      const submittedCode = shareCode.trim();
      const shared = await resolveSharedPromptList(submittedCode);
      const alreadyOwned = promptLists.some((item) =>
        item.slug === shared.slug && !item.isBundled && item.shareCode !== undefined
      );
      setPromptLists((current) => current.some((item) => item.slug === shared.slug)
        ? current
        : [...current, shared]);
      if (!alreadyOwned) {
        setSharedAccess((current) => ({
          ...current,
          [shared.slug]: { code: submittedCode, list: shared },
        }));
      }
      const selection = addSharedPromptSelection(
        selectedSlugs, shareCodes, shared, submittedCode, language
      );
      if (!selection.ok) {
        setShareError(
          ui.promptListPicker.languageMismatch({
            listLanguage: promptLanguageLabel(selection.language),
            roomLanguage: promptLanguageLabel(language),
          }),
        );
        return;
      }
      onShareCodesChange?.(selection.shareCodes);
      onChange(selection.slugs);
      setShareCode("");
    } catch (error) {
      setShareError(refusalText(error, ui.promptListPicker.couldNotAddThatSharedList));
    } finally {
      setResolvingShare(false);
    }
  }

  function handleToggle(slug: string) {
    if (disabled) return;
    if (selectedSlugs.includes(slug)) {
      // Don't deselect if it's the only one selected
      if (selectedSlugs.length <= 1) return;
      onChange(selectedSlugs.filter((s) => s !== slug));
    } else {
      // A shared list is only resolvable while its bearer code travels with
      // it, and the room drops every code when its language changes - so a
      // list still on screen from before that switch would go back into the
      // selection unauthorized and be refused on create. The code it was
      // added with is still here; it goes back with it.
      const shared = sharedAccess[slug];
      if (shared && !shareCodes.includes(shared.code)) {
        onShareCodesChange?.([...shareCodes, shared.code]);
      }
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
        <p>{ui.promptListPicker.loadingCuratedPromptLists}</p>
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
                className={`toggle-chip ${isSelected ? "is-selected" : ""}`}
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
              {/* A new tab: this picker also lives in the waiting-room settings,
                  where navigating away would discard settings the host is
                  part-way through editing. */}
              {wl.isBundled && <a
                className="prompt-list-chip-info"
                href={`/prompt-lists/${wl.slug}`}
                target="_blank"
                rel="noreferrer"
                title={ui.promptListPicker.howListPlays({ name: wl.name })}
                aria-label={ui.promptListPicker.howListPlays({ name: wl.name })}
              >
                <span aria-hidden="true"><InfoIcon size={13} /></span>
              </a>}
              {sharedAccess[wl.slug] && <button
                type="button"
                className="prompt-list-chip-report"
                disabled={disabled}
                aria-label={ui.promptListPicker.reportList({ name: wl.name })}
                title={ui.promptListPicker.reportList({ name: wl.name })}
                onClick={() => setReportingSlug(wl.slug)}
              ><AlertIcon size={13} /></button>}
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
      </>}
      <form className="prompt-list-share-form" onSubmit={(event) => void addSharedList(event)}>
        <label htmlFor="prompt-list-share-code">{ui.promptListPicker.addUnlistedListByCode}</label>
        <div><input id="prompt-list-share-code" value={shareCode} disabled={disabled || resolvingShare} maxLength={24} autoComplete="off" onChange={(event) => setShareCode(event.target.value)} /><button type="submit" className="btn btn-primary btn-compact" disabled={disabled || resolvingShare || !shareCode.trim()}>{resolvingShare ? ui.promptListPicker.adding : ui.promptListPicker.add}</button></div>
        {shareError && <p className="prompt-list-fallback-note" role="alert">{shareError}</p>}
      </form>
      {reportNotice && <p className="prompt-list-manager-notice" role="status">{reportNotice}</p>}
      {reportingSlug && sharedAccess[reportingSlug] && <PromptContentReportDialog
        promptList={sharedAccess[reportingSlug].list}
        shareCode={sharedAccess[reportingSlug].code}
        onClose={() => setReportingSlug(null)}
        onSubmitted={() => {
          setReportingSlug(null);
          setReportNotice(ui.promptListPicker.reportSentForModeratorReview);
        }}
      />}
    </fieldset>
  );
}
