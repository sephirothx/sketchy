import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiRequest } from "../lib/api";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { listOwnedPromptLists, resolveSharedPromptList } from "../lib/promptLists";
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
}

export function PromptListPicker({
  language,
  selectedSlugs,
  onChange,
  shareCodes = [],
  onShareCodesChange,
  disabled = false,
  onListsLoaded,
}: PromptListPickerProps) {
  const user = useAuthStore((state) => state.user);
  const userId = user?.id;
  const isAnonymous = user?.isAnonymous;
  const [promptLists, setPromptLists] = useState<PromptListSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [shareCode, setShareCode] = useState("");
  const [shareError, setShareError] = useState<string | null>(null);
  const [resolvingShare, setResolvingShare] = useState(false);
  const [sharedAccess, setSharedAccess] = useState<Record<string, { code: string; list: SharedPromptList }>>({});
  const [reportingSlug, setReportingSlug] = useState<string | null>(null);
  const [reportNotice, setReportNotice] = useState<string | null>(null);
  const onListsLoadedRef = useRef(onListsLoaded);

  useEffect(() => {
    onListsLoadedRef.current = onListsLoaded;
  }, [onListsLoaded]);

  useEffect(() => {
    onListsLoadedRef.current?.(promptLists);
  }, [promptLists]);

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

  const visibleLists = promptLists.filter((list) => list.language === language);

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
        {visibleLists.map((wl) => {
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
                title={wl.description || `${wl.name} (${wl.promptCount} prompts)`}
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
        })}
      </div>
      <form className="prompt-list-share-form" onSubmit={(event) => void addSharedList(event)}>
        <label htmlFor="prompt-list-share-code">{ui.promptListPicker.addUnlistedListByCode}</label>
        <div><input id="prompt-list-share-code" value={shareCode} disabled={disabled || resolvingShare} maxLength={24} autoComplete="off" onChange={(event) => setShareCode(event.target.value)} /><button type="submit" className="btn btn-primary btn-compact" disabled={disabled || resolvingShare || !shareCode.trim()}>{resolvingShare ? "Adding…" : "Add"}</button></div>
        {shareError && <p className="prompt-list-fallback-note" role="alert">{shareError}</p>}
      </form>
      {reportNotice && <p className="prompt-list-manager-notice" role="status">{reportNotice}</p>}
      {reportingSlug && sharedAccess[reportingSlug] && <PromptContentReportDialog
        promptList={sharedAccess[reportingSlug].list}
        shareCode={sharedAccess[reportingSlug].code}
        onClose={() => setReportingSlug(null)}
        onSubmitted={() => {
          setReportingSlug(null);
          setReportNotice("Report sent for moderator review.");
        }}
      />}
    </fieldset>
  );
}
