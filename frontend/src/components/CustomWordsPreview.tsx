import { useMemo, useState } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse } from "../types";

interface CustomWordsResponse extends AckResponse {
  words?: string[];
}

interface CustomWordsPreviewProps {
  count: number;
}

type LengthFilter = "all" | "short" | "medium" | "long";
type DisplayLimit = "200" | "500" | "1000" | "2000" | "5000" | "all";

const lengthFilters: { value: LengthFilter; label: string; hint: string }[] = [
  { value: "all", label: "All", hint: "All word lengths" },
  { value: "short", label: "Short", hint: "5 characters or fewer" },
  { value: "medium", label: "Medium", hint: "6 to 10 characters" },
  { value: "long", label: "Long", hint: "11 characters or more" },
];

function matchesLength(word: string, filter: LengthFilter) {
  if (filter === "short") return word.length <= 5;
  if (filter === "medium") return word.length >= 6 && word.length <= 10;
  if (filter === "long") return word.length >= 11;
  return true;
}

export function CustomWordsPreview({ count }: CustomWordsPreviewProps) {
  const [words, setWords] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [lengthFilter, setLengthFilter] = useState<LengthFilter>("all");
  const [displayLimit, setDisplayLimit] = useState<DisplayLimit>("200");

  const filteredWords = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return words.filter(
      (word) =>
        matchesLength(word, lengthFilter) &&
        (!normalizedQuery || word.toLocaleLowerCase().includes(normalizedQuery)),
    );
  }, [lengthFilter, query, words]);

  const visibleWords =
    displayLimit === "all"
      ? filteredWords
      : filteredWords.slice(0, Number(displayLimit));
  const hasFilters = Boolean(query.trim()) || lengthFilter !== "all";

  const resultSummary =
    visibleWords.length < filteredWords.length
      ? `Showing ${visibleWords.length} of ${filteredWords.length}${hasFilters ? " matching" : ""} words`
      : hasFilters
        ? `${filteredWords.length} of ${words.length} words match`
        : `${words.length} word${words.length === 1 ? "" : "s"}`;

  async function loadWords() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const response = await emitWithAck<CustomWordsResponse>("get_custom_words", {});
      if (response.ok && response.words) {
        setWords(response.words);
      } else {
        setError(response.error || "Could not load the custom words");
      }
    } catch (loadError) {
      setError(socketRequestErrorMessage(loadError, "load the custom words"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <details
      className="waiting-custom-words"
      onToggle={(event) => {
        if (event.currentTarget.open) void loadWords();
      }}
    >
      <summary>
        Inspect {count} custom word{count === 1 ? "" : "s"}
      </summary>
      <div className="waiting-custom-words-content">
        {loading ? (
          <p>Loading custom words…</p>
        ) : error ? (
          <p className="waiting-custom-words-error" role="alert">{error}</p>
        ) : (
          <>
            <div className="waiting-custom-words-heading">
              <div>
                <strong>Room word collection</strong>
                <p>Read-only list supplied by the room host.</p>
              </div>
              <span>{words.length}</span>
            </div>

            <label className="waiting-custom-words-search">
              <span>Find a word</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search custom words…"
                autoComplete="off"
              />
            </label>

            <div
              className="waiting-custom-words-filters"
              role="group"
              aria-label="Filter words by length"
            >
              {lengthFilters.map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  aria-pressed={lengthFilter === filter.value}
                  title={filter.hint}
                  onClick={() => setLengthFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>

            <div className="waiting-custom-words-results">
              <p className="waiting-custom-words-result-count" aria-live="polite">
                {resultSummary}
              </p>
              <label>
                Show
                <select
                  aria-label="Words to display"
                  value={displayLimit}
                  onChange={(event) =>
                    setDisplayLimit(event.target.value as DisplayLimit)
                  }
                >
                  <option value="200">200</option>
                  <option value="500">500</option>
                  <option value="1000">1,000</option>
                  <option value="2000">2,000</option>
                  <option value="5000">5,000</option>
                  <option value="all">All</option>
                </select>
              </label>
            </div>

            {filteredWords.length ? (
              <div className="waiting-custom-words-list" role="list">
                {visibleWords.map((word, index) => (
                  <span key={`${word}-${index}`} role="listitem">{word}</span>
                ))}
              </div>
            ) : (
              <p className="waiting-custom-words-empty">
                No custom words match these filters.
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}
