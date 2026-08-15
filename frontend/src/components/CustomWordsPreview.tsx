import { useLayoutEffect, useMemo, useRef, useState } from "react";
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
type LengthBucket = Exclude<LengthFilter, "all">;

interface WordRecord {
  word: string;
  normalized: string;
  lengthBucket: LengthBucket;
}

const lengthFilters: { value: LengthFilter; label: string; hint: string }[] = [
  { value: "all", label: "All", hint: "All word lengths" },
  { value: "short", label: "Short", hint: "5 characters or fewer" },
  { value: "medium", label: "Medium", hint: "6 to 10 characters" },
  { value: "long", label: "Long", hint: "11 characters or more" },
];

function createWordRecord(word: string): WordRecord {
  const lengthBucket = word.length <= 5
    ? "short"
    : word.length <= 10
      ? "medium"
      : "long";
  return { word, normalized: word.toLocaleLowerCase(), lengthBucket };
}

const VIRTUALIZE_ABOVE = 250;
const VIRTUAL_ROW_HEIGHT = 36;
const VIRTUAL_ITEM_MIN_WIDTH = 130;
const VIRTUAL_GAP = 6;
const VIRTUAL_OVERSCAN_ROWS = 3;

function VirtualWordList({ records }: { records: WordRecord[] }) {
  const listRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({
    height: 190,
    scrollTop: 0,
    width: VIRTUAL_ITEM_MIN_WIDTH,
  });

  useLayoutEffect(() => {
    const element = listRef.current;
    if (!element) return;
    const updateSize = () => setViewport((current) => ({
      ...current,
      height: element.clientHeight,
      width: element.clientWidth,
    }));
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const columns = Math.max(
    1,
    Math.floor(
      (viewport.width + VIRTUAL_GAP) /
        (VIRTUAL_ITEM_MIN_WIDTH + VIRTUAL_GAP),
    ),
  );
  const rowCount = Math.ceil(records.length / columns);
  const firstRow = Math.max(
    0,
    Math.floor(viewport.scrollTop / VIRTUAL_ROW_HEIGHT) - VIRTUAL_OVERSCAN_ROWS,
  );
  const lastRow = Math.min(
    rowCount,
    Math.ceil((viewport.scrollTop + viewport.height) / VIRTUAL_ROW_HEIGHT) +
      VIRTUAL_OVERSCAN_ROWS,
  );
  const rows = Array.from(
    { length: Math.max(0, lastRow - firstRow) },
    (_, offset) => firstRow + offset,
  );

  return (
    <div
      ref={listRef}
      className="waiting-custom-words-list is-virtualized"
      role="list"
      tabIndex={0}
      aria-label={`${records.length} custom words`}
      onScroll={(event) => {
        const element = event.currentTarget;
        setViewport((current) => ({
          ...current,
          height: element.clientHeight,
          scrollTop: element.scrollTop,
          width: element.clientWidth,
        }));
      }}
    >
      <div
        className="waiting-custom-words-virtual-space"
        style={{ height: rowCount * VIRTUAL_ROW_HEIGHT }}
      >
        {rows.map((row) => {
          const rowRecords = records.slice(row * columns, (row + 1) * columns);
          return (
            <div
              key={row}
              className="waiting-custom-words-virtual-row"
              role="presentation"
              style={{
                gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                transform: `translateY(${row * VIRTUAL_ROW_HEIGHT}px)`,
              }}
            >
              {rowRecords.map((record, column) => (
                <span
                  key={record.word}
                  role="listitem"
                  aria-posinset={row * columns + column + 1}
                  aria-setsize={records.length}
                >
                  {record.word}
                </span>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CustomWordsPreview({ count }: CustomWordsPreviewProps) {
  const [words, setWords] = useState<WordRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [lengthFilter, setLengthFilter] = useState<LengthFilter>("all");
  const [displayLimit, setDisplayLimit] = useState<DisplayLimit>("200");

  const filteredWords = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return words.filter(
      (record) =>
        (lengthFilter === "all" || record.lengthBucket === lengthFilter) &&
        (!normalizedQuery || record.normalized.includes(normalizedQuery)),
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
        setWords(response.words.map(createWordRecord));
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

            {filteredWords.length && visibleWords.length > VIRTUALIZE_ABOVE ? (
              <VirtualWordList
                key={`${query}\u0000${lengthFilter}\u0000${displayLimit}`}
                records={visibleWords}
              />
            ) : filteredWords.length ? (
              <div className="waiting-custom-words-list" role="list">
                {visibleWords.map((record) => (
                  <span key={record.word} role="listitem">{record.word}</span>
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
