import { useEffect, useState, type FormEvent } from "react";
import { apiRequest } from "../lib/api";
import { promptLanguageLabel } from "../lib/promptLanguages";
import { listOwnedPromptLists, resolveSharedPromptList } from "../lib/promptLists";
import { addSharedPromptSelection } from "../lib/promptListDrafts";
import { useAuthStore } from "../store/authStore";
import type { PromptLanguage, PromptListSummary } from "../types";

interface PromptListPickerProps {
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  shareCodes?: string[];
  onShareCodesChange?: (codes: string[]) => void;
  disabled?: boolean;
}

export function PromptListPicker({
  selectedSlugs,
  onChange,
  shareCodes = [],
  onShareCodesChange,
  disabled = false,
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
          setFetchError(err instanceof Error ? err.message : "Failed to load prompt lists");
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
      const shared = await resolveSharedPromptList(shareCode);
      setPromptLists((current) => current.some((item) => item.slug === shared.slug)
        ? current
        : [...current, shared]);
      const selection = addSharedPromptSelection(
        selectedSlugs, shareCodes, shared, shareCode, activeLanguage
      );
      onShareCodesChange?.(selection.shareCodes);
      onChange(selection.slugs);
      setShareCode("");
    } catch (error) {
      setShareError(error instanceof Error ? error.message : "Could not add that shared list.");
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
      onChange([...selectedSlugs, slug]);
    }
  }

  const selectedList = promptLists.find((list) => selectedSlugs.includes(list.slug));
  const activeLanguage = selectedList?.language
    ?? promptLists.find((list) => list.language === "en")?.language
    ?? promptLists[0]?.language
    ?? "en";
  const languages = [...new Set(promptLists.map((list) => list.language))]
    .sort((left, right) => promptLanguageLabel(left).localeCompare(promptLanguageLabel(right)));
  const visibleLists = promptLists.filter((list) => list.language === activeLanguage);

  function handleLanguage(language: PromptLanguage) {
    if (disabled || language === activeLanguage) return;
    const firstList = promptLists.find((list) => list.language === language);
    if (firstList) onChange([firstList.slug]);
  }

  if (loading) {
    return (
      <div className="prompt-list-picker-loading">
        <p>Loading curated prompt lists…</p>
      </div>
    );
  }

  if (fetchError && promptLists.length === 0) {
    return (
      <div className="prompt-list-picker-fallback">
        <p className="prompt-list-fallback-note">
          Prompt-list choices are unavailable ({fetchError}). Your current selection is unchanged.
        </p>
      </div>
    );
  }

  return (
    <fieldset className="room-choice-group prompt-list-picker-group">
      <legend>Prompt lists</legend>
      <div className="prompt-list-language-row">
        <label htmlFor="prompt-list-language">Prompt language</label>
        {languages.length > 1 ? (
          <select
            id="prompt-list-language"
            value={activeLanguage}
            disabled={disabled}
            onChange={(event) => handleLanguage(event.target.value as PromptLanguage)}
          >
            {languages.map((language) => (
              <option key={language} value={language}>
                {promptLanguageLabel(language)}
              </option>
            ))}
          </select>
        ) : (
          <output>{promptLanguageLabel(activeLanguage)}</output>
        )}
      </div>
      <div className="toggle-chips" role="group" aria-label="Prompt lists">
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
                  {isSelected ? "✓" : "+"}
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
                title={`How ${wl.name} prompts play`}
                aria-label={`How ${wl.name} prompts play`}
              >
                <span aria-hidden="true">i</span>
              </a>}
            </span>
          );
        })}
      </div>
      <form className="prompt-list-share-form" onSubmit={(event) => void addSharedList(event)}>
        <label htmlFor="prompt-list-share-code">Add an unlisted list by code</label>
        <div><input id="prompt-list-share-code" value={shareCode} disabled={disabled || resolvingShare} maxLength={24} autoComplete="off" onChange={(event) => setShareCode(event.target.value)} /><button type="submit" disabled={disabled || resolvingShare || !shareCode.trim()}>{resolvingShare ? "Adding…" : "Add"}</button></div>
        {shareError && <p className="prompt-list-fallback-note" role="alert">{shareError}</p>}
      </form>
    </fieldset>
  );
}
