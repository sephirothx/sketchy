import { useEffect, useState } from "react";
import type { WordListSummary } from "../types";

interface WordListPickerProps {
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  disabled?: boolean;
}

export function WordListPicker({ selectedSlugs, onChange, disabled = false }: WordListPickerProps) {
  const [wordLists, setWordLists] = useState<WordListSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadLists() {
      try {
        const res = await fetch("/api/word-lists");
        if (!res.ok) {
          throw new Error(`Failed to load word lists (${res.status})`);
        }
        const data: WordListSummary[] = await res.json();
        if (!cancelled) {
          setWordLists(data);
        }
      } catch (err) {
        if (!cancelled) {
          setFetchError(err instanceof Error ? err.message : "Failed to load word lists");
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
  }, []);

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

  if (loading) {
    return (
      <div className="word-list-picker-loading">
        <p>Loading curated word lists…</p>
      </div>
    );
  }

  if (fetchError && wordLists.length === 0) {
    return (
      <div className="word-list-picker-fallback">
        <p className="word-list-fallback-note">Using default word list ({fetchError})</p>
      </div>
    );
  }

  return (
    <fieldset className="room-choice-group word-list-picker-group">
      <legend>Word lists</legend>
      <div className="word-list-chips" role="group" aria-label="Word lists">
        {wordLists.map((wl) => {
          const isSelected = selectedSlugs.includes(wl.slug);
          const isOnlySelected = isSelected && selectedSlugs.length <= 1;

          return (
            <button
              key={wl.slug}
              type="button"
              className={`word-list-chip ${isSelected ? "is-selected" : ""}`}
              aria-pressed={isSelected}
              disabled={disabled || (isSelected && isOnlySelected)}
              title={wl.description || `${wl.name} (${wl.wordCount} words)`}
              onClick={() => handleToggle(wl.slug)}
            >
              <span className="word-list-chip-status" aria-hidden="true">
                {isSelected ? "✓" : "+"}
              </span>
              <span className="word-list-chip-name">{wl.name}</span>
              <span className="word-list-chip-count">{wl.wordCount}</span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
