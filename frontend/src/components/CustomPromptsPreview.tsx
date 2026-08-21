import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { useEscapeLayer } from "../hooks/useFocusTrap";
import type { AckResponse } from "../types";

interface CustomPromptsResponse extends AckResponse {
  prompts?: string[];
}

interface CustomWordsPreviewProps {
  count: number;
}

type LengthFilter = "all" | "short" | "medium" | "long";
type LengthBucket = Exclude<LengthFilter, "all">;

interface PromptRecord {
  prompt: string;
  normalized: string;
  lengthBucket: LengthBucket;
}

interface ActivePrompt {
  anchor: HTMLSpanElement;
  prompt: string;
}

const lengthFilters: { value: LengthFilter; label: string; hint: string }[] = [
  { value: "all", label: "All", hint: "All prompt lengths" },
  { value: "short", label: "Short", hint: "5 characters or fewer" },
  { value: "medium", label: "Medium", hint: "6 to 10 characters" },
  { value: "long", label: "Long", hint: "11 characters or more" },
];

function createPromptRecord(prompt: string): PromptRecord {
  const lengthBucket = prompt.length <= 5
    ? "short"
    : prompt.length <= 10
      ? "medium"
      : "long";
  return { prompt, normalized: prompt.toLocaleLowerCase(), lengthBucket };
}

const VIRTUALIZE_ABOVE = 250;
const VIRTUAL_ROW_HEIGHT = 36;
const VIRTUAL_ITEM_MIN_WIDTH = 130;
const VIRTUAL_GAP = 6;
const VIRTUAL_OVERSCAN_ROWS = 3;
const FULL_WORD_TOOLTIP_ID = "custom-prompt-full-text-tooltip";

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
  activePrompt: ActivePrompt | null;
  onDismiss: (anchor?: HTMLSpanElement) => void;
  onShow: (prompt: string, anchor: HTMLSpanElement) => void;
  position?: number;
  record: PromptRecord;
  total?: number;
}

function WordChip({
  activePrompt,
  onDismiss,
  onShow,
  position,
  record,
  total,
}: WordChipProps) {
  const isActive = activePrompt?.prompt === record.prompt;
  return (
    <span
      role="listitem"
      tabIndex={0}
      aria-describedby={isActive ? FULL_WORD_TOOLTIP_ID : undefined}
      aria-posinset={position}
      aria-setsize={total}
      onBlur={(event) => onDismiss(event.currentTarget)}
      onClick={(event) => onShow(record.prompt, event.currentTarget)}
      onFocus={(event) => onShow(record.prompt, event.currentTarget)}
      onMouseEnter={(event) => onShow(record.prompt, event.currentTarget)}
      onMouseLeave={(event) => {
        if (document.activeElement !== event.currentTarget) {
          onDismiss(event.currentTarget);
        }
      }}
    >
      {record.prompt}
    </span>
  );
}

function FullWordTooltip({ activePrompt }: { activePrompt: ActivePrompt }) {
  const [position, setPosition] = useState({ left: 0, top: 0, above: false });

  useLayoutEffect(() => {
    const updatePosition = () => {
      const rect = activePrompt.anchor.getBoundingClientRect();
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
  }, [activePrompt]);

  return createPortal(
    <div
      id={FULL_WORD_TOOLTIP_ID}
      className="custom-prompt-full-text-tooltip"
      role="tooltip"
      style={{
        left: position.left,
        top: position.top,
        transform: position.above ? "translate(-50%, -100%)" : "translateX(-50%)",
      }}
    >
      {activePrompt.prompt}
    </div>,
    document.body,
  );
}

interface VirtualWordListProps {
  activePrompt: ActivePrompt | null;
  onDismiss: (anchor?: HTMLSpanElement) => void;
  onShow: (prompt: string, anchor: HTMLSpanElement) => void;
  records: PromptRecord[];
}

function VirtualWordList({ activePrompt, onDismiss, onShow, records }: VirtualWordListProps) {
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
      className="waiting-custom-prompts-list is-virtualized"
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
        className="waiting-custom-prompts-virtual-space"
        style={{ height: rowCount * VIRTUAL_ROW_HEIGHT }}
      >
        {rows.map((row) => {
          const rowRecords = records.slice(row * columns, (row + 1) * columns);
          return (
            <div
              key={row}
              className="waiting-custom-prompts-virtual-row"
              role="presentation"
              style={{
                gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                transform: `translateY(${row * VIRTUAL_ROW_HEIGHT}px)`,
              }}
            >
              {rowRecords.map((record, column) => (
                <WordChip
                  key={record.prompt}
                  activePrompt={activePrompt}
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

export function CustomPromptsPreview({ count }: CustomWordsPreviewProps) {
  const [prompts, setPrompts] = useState<PromptRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [lengthFilter, setLengthFilter] = useState<LengthFilter>("all");
  const [activePrompt, setActivePrompt] = useState<ActivePrompt | null>(null);

  function showFullPrompt(prompt: string, anchor: HTMLSpanElement) {
    if (!hasTruncatedText(anchor)) {
      setActivePrompt((current) => current?.anchor === anchor ? null : current);
      return;
    }
    setActivePrompt({ anchor, prompt });
  }

  function dismissFullWord(anchor?: HTMLSpanElement) {
    setActivePrompt((current) =>
      !anchor || current?.anchor === anchor ? null : current,
    );
  }

  useEscapeLayer(activePrompt !== null, () => setActivePrompt(null));

  useEffect(() => {
    if (!activePrompt) return;
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!activePrompt.anchor.contains(event.target as Node)) setActivePrompt(null);
    };
    document.addEventListener("pointerdown", dismissOnPointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown, true);
    };
  }, [activePrompt]);

  const filteredPrompts = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return prompts.filter(
      (record) =>
        (lengthFilter === "all" || record.lengthBucket === lengthFilter) &&
        (!normalizedQuery || record.normalized.includes(normalizedQuery)),
    );
  }, [lengthFilter, query, prompts]);

  const hasFilters = Boolean(query.trim()) || lengthFilter !== "all";

  const resultSummary = hasFilters
    ? `${filteredPrompts.length} of ${prompts.length} prompts match`
    : `${prompts.length} prompt${prompts.length === 1 ? "" : "s"}`;

  async function loadPrompts() {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const response = await emitWithAck<CustomPromptsResponse>("get_custom_prompts", {});
      if (response.ok && response.prompts) {
        setPrompts(response.prompts.map(createPromptRecord));
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
      className="waiting-custom-prompts"
      onToggle={(event) => {
        if (event.currentTarget.open) void loadPrompts();
      }}
    >
      <summary>
        Inspect {count} custom prompt{count === 1 ? "" : "s"}
      </summary>
      <div className="waiting-custom-prompts-content">
        {loading ? (
          <p>Loading custom prompts…</p>
        ) : error ? (
          <p className="waiting-custom-prompts-error" role="alert">{error}</p>
        ) : (
          <>
            <div className="waiting-custom-prompts-heading">
              <div>
                <strong>Room prompt collection</strong>
                <p>Read-only list supplied by the room host.</p>
              </div>
              <span>{prompts.length}</span>
            </div>

            <label className="waiting-custom-prompts-search">
              <span>Find a prompt</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search custom prompts…"
                autoComplete="off"
              />
            </label>

            <div
              className="waiting-custom-prompts-filters"
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

            <p className="waiting-custom-prompts-result-count" aria-live="polite">
              {resultSummary}
            </p>

            {filteredPrompts.length > VIRTUALIZE_ABOVE ? (
              <VirtualWordList
                key={`${query}\u0000${lengthFilter}`}
                activePrompt={activePrompt}
                onDismiss={dismissFullWord}
                onShow={showFullPrompt}
                records={filteredPrompts}
              />
            ) : filteredPrompts.length ? (
              <div
                className="waiting-custom-prompts-list"
                role="list"
                onScroll={() => dismissFullWord()}
              >
                {filteredPrompts.map((record) => (
                  <WordChip
                    key={record.prompt}
                    activePrompt={activePrompt}
                    onDismiss={dismissFullWord}
                    onShow={showFullPrompt}
                    record={record}
                  />
                ))}
              </div>
            ) : (
              <p className="waiting-custom-prompts-empty">
                No custom prompts match these filters.
              </p>
            )}
            {activePrompt && <FullWordTooltip activePrompt={activePrompt} />}
          </>
        )}
      </div>
    </details>
  );
}
