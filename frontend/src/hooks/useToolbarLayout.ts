import { type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ARRANGEMENTS,
  arrangementOf,
  chooseToolbarLayout,
  type ToolbarLayout,
  type ToolbarMetrics,
} from "../lib/toolbarLayout";

function width(element: Element): number {
  return element.getBoundingClientRect().width;
}

function px(value: string): number {
  return parseFloat(value) || 0;
}

/** What the column leaves for the card: its box less its padding and border. */
function contentWidth(column: HTMLElement): number {
  const style = getComputedStyle(column);
  return (
    width(column)
    - px(style.paddingLeft) - px(style.paddingRight)
    - px(style.borderLeftWidth) - px(style.borderRightWidth)
  );
}

/**
 * Undo and Clear both ways, whichever is on screen. A hidden name stays laid
 * out (toolbar.css), so its width reads the same either way and neither sum
 * depends on the arrangement that happened to be measured.
 */
function actionWidths(group: HTMLElement, iconsShown: boolean) {
  const buttons = [...group.children];
  let named = px(getComputedStyle(group).columnGap) * Math.max(0, buttons.length - 1);
  let icons = named;
  for (const button of buttons) {
    const label = button.querySelector(".toolbar-action-label");
    const name = label ? width(label) + px(getComputedStyle(button).columnGap) : 0;
    const shown = width(button);
    named += iconsShown ? shown + name : shown;
    icons += iconsShown ? shown : shown - name;
  }
  return { named, icons };
}

function measure(card: HTMLElement, layout: ToolbarLayout): ToolbarMetrics | null {
  const toolbar = card.querySelector(".toolbar");
  const tools = card.querySelector(".toolbar-tools");
  const size = card.querySelector(".brush-size-dropdown");
  const palette = card.querySelector(".toolbar-colors");
  const actions = card.querySelector<HTMLElement>(".toolbar-actions");
  // Tools and size open the first line of every arrangement, so there is
  // always this one divider to read the spacing off.
  const divider = card.querySelector(".toolbar-divider");
  if (!toolbar || !tools || !size || !palette || !actions || !divider) return null;
  const { named, icons } = actionWidths(actions, arrangementOf(layout)?.iconActions ?? false);
  const dividerStyle = getComputedStyle(divider);
  return {
    tools: width(tools),
    size: width(size),
    palette: width(palette),
    actions: named,
    actionIcons: icons,
    separator:
      2 * px(getComputedStyle(toolbar).columnGap)
      + width(divider) + px(dividerStyle.marginLeft) + px(dividerStyle.marginRight),
    chrome: width(card) - width(toolbar),
  };
}

function settle(
  layout: ToolbarLayout,
  card: HTMLElement | null,
  compact: HTMLElement | null,
  metrics: { current: ToolbarMetrics | null },
): ToolbarLayout {
  const column = (card ?? compact)?.parentElement;
  if (!column) return layout;
  if (card) metrics.current = measure(card, layout) ?? metrics.current;
  if (!metrics.current) return layout;
  return chooseToolbarLayout(metrics.current, contentWidth(column));
}

/**
 * The desktop toolbar's arrangement, re-chosen whenever its column or its
 * contents change width. Why it is measured is in lib/toolbarLayout.ts.
 *
 * `card` is the full toolbar's `.toolbar-container` and `compact` the chip
 * strip's; exactly one of them is mounted. The strip has nothing to measure,
 * so the widths the full toolbar last had stand in for it. If those have gone
 * stale the full toolbar comes back, is measured, and - not fitting after all -
 * goes again inside the same layout pass, before anything is painted.
 */
export function useToolbarLayout(
  enabled: boolean,
  card: RefObject<HTMLDivElement | null>,
  compact: RefObject<HTMLDivElement | null>,
): ToolbarLayout {
  // Widest first: everything laid out on one line is what the first
  // measurement reads, and the layout effect replaces it before it is shown.
  const [layout, setLayout] = useState<ToolbarLayout>(ARRANGEMENTS[0].layout);
  const metrics = useRef<ToolbarMetrics | null>(null);

  // After every render and before the paint: a language, a tool the host took
  // away, or the size readout can each change what fits, and none of them is
  // this hook's to list. It cannot chain: the choice is a pure function of the
  // widths, so the render it triggers settles on the same answer and stops.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useLayoutEffect(() => {
    if (!enabled) return;
    const next = settle(layout, card.current, compact.current, metrics);
    if (next !== layout) setLayout(next);
  });

  // What changes width without a render: the column, as the window is
  // resized, and a label whose font finishes loading.
  useEffect(() => {
    if (!enabled || typeof ResizeObserver === "undefined") return;
    const root = card.current ?? compact.current;
    const column = root?.parentElement;
    if (!root || !column) return;
    const observer = new ResizeObserver(() => {
      setLayout(settle(layout, card.current, compact.current, metrics));
    });
    observer.observe(column);
    for (const group of root.querySelectorAll(".toolbar-group")) observer.observe(group);
    return () => observer.disconnect();
  }, [enabled, layout, card, compact]);

  return layout;
}
