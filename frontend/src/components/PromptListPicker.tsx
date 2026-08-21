import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import type { PromptListSummary } from "../types";

interface PromptListPickerProps {
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
  disabled?: boolean;
}

export function PromptListPicker({ selectedSlugs, onChange, disabled = false }: PromptListPickerProps) {
  const [promptLists, setPromptLists] = useState<PromptListSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadLists() {
      try {
        const data = await apiRequest<PromptListSummary[]>("/api/prompt-lists");
        if (!cancelled) {
          setPromptLists(data);
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
      <div className="prompt-list-picker-loading">
        <p>Loading curated prompt lists…</p>
      </div>
    );
  }

  if (fetchError && promptLists.length === 0) {
    return (
      <div className="prompt-list-picker-fallback">
        <p className="prompt-list-fallback-note">Using default prompt list ({fetchError})</p>
      </div>
    );
  }

  return (
    <fieldset className="room-choice-group prompt-list-picker-group">
      <legend>Prompt lists</legend>
      <div className="prompt-list-chips" role="group" aria-label="Prompt lists">
        {promptLists.map((wl) => {
          const isSelected = selectedSlugs.includes(wl.slug);
          const isOnlySelected = isSelected && selectedSlugs.length <= 1;

          return (
            <button
              key={wl.slug}
              type="button"
              className={`prompt-list-chip ${isSelected ? "is-selected" : ""}`}
              aria-pressed={isSelected}
              disabled={disabled || (isSelected && isOnlySelected)}
              title={wl.description || `${wl.name} (${wl.promptCount} prompts)`}
              onClick={() => handleToggle(wl.slug)}
            >
              <span className="prompt-list-chip-status" aria-hidden="true">
                {isSelected ? "✓" : "+"}
              </span>
              <span className="prompt-list-chip-name">{wl.name}</span>
              <span className="prompt-list-chip-count">{wl.promptCount}</span>
            </button>
          );
        })}
      </div>
      <p className="prompt-list-stats-links">
        {/* A new tab rather than a route change: this picker also lives inside
            the waiting-room settings dialog, where navigating away would throw
            out settings the host is part-way through editing. */}
        See how they play:{" "}
        {promptLists.map((wl, index) => (
          <span key={wl.slug}>
            {index > 0 ? " · " : ""}
            <a
              href={`/prompt-lists/${wl.slug}`}
              target="_blank"
              rel="noreferrer"
            >
              {wl.name}
            </a>
          </span>
        ))}
      </p>
    </fieldset>
  );
}
