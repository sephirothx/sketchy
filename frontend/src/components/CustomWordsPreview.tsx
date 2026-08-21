import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import type { AckResponse } from "../types";

interface CustomWordsResponse extends AckResponse {
  words?: string[];
}

interface CustomWordsPreviewProps {
  count: number;
}

type LengthFilter = "all" | "short" | "medium" | "long";
type LengthBucket = Exclude<LengthFilter, "all">;

interface WordRecord {
  word: string;
  normalized: string;
  lengthBucket: LengthBucket;
}

interface ActiveWord {
  anchor: HTMLSpanElement;
  word: string;
}

const lengthFilters: { value: LengthFilter; label: string; hint: string }[] = [
  { value: "all", label: "All", hint: "All prompt lengths" },
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
const FULL_WORD_TOOLTIP_ID = "custom-word-full-text-tooltip";

function hasTruncatedText(element: HTMLSpanElement) {
  const styles = getComputedStyle(element);
  if (
    styles.textOverflow !== "ellipsis" ||
    styles.whiteSpace !== "nowrap" ||
    (styles.overflowX !== "hidden" && styles.overflowX !== "clip")
  ) {
    return false;
  }
  if (element.scrollWidth > element.clientWidth) return true;

  // scrollWidth/clientWidth are integer-rounded, while the grid and text layout
  // can differ by a fraction of a pixel and still paint an ellipsis.
  const contentWidth =
    element.getBoundingClientRect().width -
    (Number.parseFloat(styles.borderLeftWidth) || 0) -
    (Number.parseFloat(styles.borderRightWidth) || 0) -
    (Number.parseFloat(styles.paddingLeft) || 0) -
    (Number.parseFloat(styles.paddingRight) || 0);
  const textRange = document.createRange();
  textRange.selectNodeContents(element);
  return textRange.getBoundingClientRect().width > contentWidth;
}

interface WordChipProps {
  activeWord: ActiveWord | null;
  onDismiss: (anchor?: HTMLSpanElement) => void;
  onShow: (word: string, anchor: HTMLSpanElement) => void;
  position?: number;
  record: WordRecord;
  total?: number;
}

function WordChip({
  activeWord,
  onDismiss,
  onShow,
  position,
  record,
  total,
}: WordChipProps) {
  const isActive = activeWord?.word === record.word;
  return (
    <span
      role="listitem"
      tabIndex={0}
      aria-describedby={isActive ? FULL_WORD_TOOLTIP_ID : undefined}
      aria-posinset={position}
      aria-setsize={total}
      onBlur={(event) => onDismiss(event.currentTarget)}
      onClick={(event) => onShow(record.word, event.currentTarget)}
      onFocus={(event) => onShow(record.word, event.currentTarget)}
      onMouseEnter={(event) => onShow(record.word, event.currentTarget)}
      onMouseLeave={(event) => {
        if (document.activeElement !== event.currentTarget) {
          onDismiss(event.currentTarget);
        }
      }}
    >
      {record.word}
    </span>
  );
}

function FullWordTooltip({ activeWord }: { activeWord: ActiveWord }) {
  const [position, setPosition] = useState({ left: 0, top: 0, above: false });

  useLayoutEffect(() => {
    const updatePosition = () => {
      const rect = activeWord.anchor.getBoundingClientRect();
      const maxWidth = Math.min(360, window.innerWidth - 16);
      const left = Math.min(
        window.innerWidth - 8 - maxWidth / 2,
        Math.max(8 + maxWidth / 2, rect.left + rect.width / 2),
      );
      const above = window.innerHeight - rect.bottom < 72 && rect.top > 72;
      setPosition({
        above,
        left,
        top: above ? rect.top - 8 : rect.bottom + 8,
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [activeWord]);

  return createPortal(
    <div
      id={FULL_WORD_TOOLTIP_ID}
      className="custom-word-full-text-tooltip"
      role="tooltip"
      style={{
        left: position.left,
        top: position.top,
        transform: position.above ? "translate(-50%, -100%)" : "translateX(-50%)",
      }}
    >
      {activeWord.word}
    </div>,
    document.body,
  );
}

interface VirtualWordListProps {
  activeWord: ActiveWord | null;
  onDismiss: (anchor?: HTMLSpanElement) => void;
  onShow: (word: string, anchor: HTMLSpanElement) => void;
  records: WordRecord[];
}

function VirtualWordList({ activeWord, onDismiss, onShow, records }: VirtualWordListProps) {
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
      aria-label={`${records.length} custom prompts`}
      onScroll={(event) => {
        onDismiss();
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
                <WordChip
                  key={record.word}
                  activeWord={activeWord}
                  onDismiss={onDismiss}
                  onShow={onShow}
                  position={row * columns + column + 1}
                  record={record}
                  total={records.length}
                />
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
  const [activeWord, setActiveWord] = useState<ActiveWord | null>(null);

  function showFullWord(word: string, anchor: HTMLSpanElement) {
    if (!hasTruncatedText(anchor)) {
      setActiveWord((current) => current?.anchor === anchor ? null : current);
      return;
    }
    setActiveWord({ anchor, word });
  }

  function dismissFullWord(anchor?: HTMLSpanElement) {
    setActiveWord((current) =>
      !anchor || current?.anchor === anchor ? null : current,
    );
  }

  useEscapeLayer(activeWord !== null, () => setActiveWord(null));

  useEffect(() => {
    if (!activeWord) return;
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!activeWord.anchor.contains(event.target as Node)) setActiveWord(null);
    };
    document.addEventListener("pointerdown", dismissOnPointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown, true);
    };
  }, [activeWord]);

  const filteredWords = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return words.filter(
      (record) =>
        (lengthFilter === "all" || record.lengthBucket === lengthFilter) &&
        (!normalizedQuery || record.normalized.includes(normalizedQuery)),
    );
  }, [lengthFilter, query, words]);

  const hasFilters = Boolean(query.trim()) || lengthFilter !== "all";

  const resultSummary = hasFilters
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
        setError(response.error || "Could not load the custom prompts");
      }
    } catch (loadError) {
      setError(socketRequestErrorMessage(loadError, "load the custom prompts"));
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
        Inspect {count} custom prompt{count === 1 ? "" : "s"}
      </summary>
      <div className="waiting-custom-words-content">
        {loading ? (
          <p>Loading custom prompts…</p>
        ) : error ? (
          <p className="waiting-custom-words-error" role="alert">{error}</p>
        ) : (
          <>
            <div className="waiting-custom-words-heading">
              <div>
                <strong>Room prompt collection</strong>
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
                placeholder="Search custom prompts…"
                autoComplete="off"
              />
            </label>

            <div
              className="waiting-custom-words-filters"
              role="group"
              aria-label="Filter prompts by length"
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

            <p className="waiting-custom-words-result-count" aria-live="polite">
              {resultSummary}
            </p>

            {filteredWords.length > VIRTUALIZE_ABOVE ? (
              <VirtualWordList
                key={`${query}\u0000${lengthFilter}`}
                activeWord={activeWord}
                onDismiss={dismissFullWord}
                onShow={showFullWord}
                records={filteredWords}
              />
            ) : filteredWords.length ? (
              <div
                className="waiting-custom-words-list"
                role="list"
                onScroll={() => dismissFullWord()}
              >
                {filteredWords.map((record) => (
                  <WordChip
                    key={record.word}
                    activeWord={activeWord}
                    onDismiss={dismissFullWord}
                    onShow={showFullWord}
                    record={record}
                  />
                ))}
              </div>
            ) : (
              <p className="waiting-custom-words-empty">
                No custom prompts match these filters.
              </p>
            )}
            {activeWord && <FullWordTooltip activeWord={activeWord} />}
          </>
        )}
      </div>
    </details>
  );
}
