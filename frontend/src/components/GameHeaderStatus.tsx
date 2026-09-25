import { useLayoutEffect, useRef, useState } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { Chip } from "./ui/Chip";
import { Timer } from "./Timer";
import { useGameStore } from "../store/gameStore";
import { useRoomStage } from "../hooks/useServerNotices";
import { ui } from "../content/ui/index.ts";

/** The boxes a flex container lays out: `display: contents` wrappers stand
    for their children, and hidden or out-of-flow elements take no room. */
function flexItems(container: Element): HTMLElement[] {
  return Array.from(container.children).flatMap((child) => {
    const style = getComputedStyle(child);
    if (style.display === "contents") return flexItems(child);
    if (style.display === "none" || style.position === "absolute" || style.position === "fixed") return [];
    return [child as HTMLElement];
  });
}

function rowWidth(items: HTMLElement[], container: Element): number {
  const gap = parseFloat(getComputedStyle(container).columnGap) || 0;
  return items.reduce((sum, item) => sum + item.getBoundingClientRect().width, 0)
    + gap * Math.max(0, items.length - 1);
}

/**
 * Whether the bar has room for the round's full label, measured rather than
 * guessed: the words are the catalogue's, seven languages long, and what sits
 * beside the chip - a notice, the Away chip, a wordmark that gives way to
 * them - changes while a game runs. Adds up the bar as it is laid out now,
 * with the chip at its full label's width whichever label is showing, so
 * the answer does not depend on the answer and cannot flip back and forth.
 */
function fullRoundFits(bar: HTMLElement, chip: HTMLElement): boolean {
  const full = chip.querySelector(".game-header-round-long");
  const short = chip.querySelector(".game-header-round-short");
  const center = bar.querySelector(".game-header-center");
  if (!full || !short || !center) return true;
  const fullWidth = full.getBoundingClientRect().width;
  const shownWidth = (chip.classList.contains("is-short") ? short : full).getBoundingClientRect().width;
  const grow = fullWidth - shownWidth;
  const barStyle = getComputedStyle(bar);
  const available = bar.clientWidth - parseFloat(barStyle.paddingLeft) - parseFloat(barStyle.paddingRight);
  const beside = flexItems(bar).filter((item) => item !== center);
  const gap = parseFloat(barStyle.columnGap) || 0;
  const needed = beside.reduce((sum, item) => sum + item.getBoundingClientRect().width, 0)
    + gap * beside.length
    + rowWidth(flexItems(center), center)
    + grow;
  // Half a pixel for the rounding of fractional widths.
  return needed <= available + 0.5;
}

/**
 * The header's center slot during play: round chip + countdown ring. Its own
 * component so the phase/round subscriptions re-render this slot, not the
 * whole room chrome.
 *
 * A phone's round reads "Round 2/3", and "2/3" when the bar has no room for
 * the word beside the wordmark, the clock, any notice and the menu - never
 * "R2/3", which read as a code. The word is the first thing on the bar to go,
 * so it never pushes the wordmark or the clock (R-UX-11). Both labels are
 * rendered and the chip says which shows; the bar is measured on mount and
 * on every change of its size or content. The mount measure lands before the
 * first paint; a later change (a notice arriving, a resize) is a state update
 * React schedules, so the old label may stand for a frame before it follows.
 *
 * The ring runs on a phone too. A game scored on seconds should not put its
 * clock in 12px of grey text, and the turn bar's numeral is what covers the
 * moment the keyboard hides this band.
 */
export function GameHeaderStatus() {
  const isMobile = useMediaQuery("(max-width: 900px)");
  const roomState = useGameStore((s) => s.roomState);
  const phase = useGameStore((s) => s.phase);
  const roundNumber = useGameStore((s) => s.roundNumber);
  const totalRounds = useGameStore((s) => s.totalRounds);
  const phaseSeconds = useGameStore((s) => s.phaseSeconds);
  const phaseStartedAt = useGameStore((s) => s.phaseStartedAt);
  const phaseDurationSeconds = useGameStore((s) => s.phaseDurationSeconds);
  const clockPaused = useRoomStage().kind !== "live";
  const chipRef = useRef<HTMLSpanElement | null>(null);
  const [fullFits, setFullFits] = useState(true);

  const shown = !(roomState !== "playing" || phase === "idle" || phase === "game_end");
  const measured = shown && isMobile;

  useLayoutEffect(() => {
    const chip = chipRef.current;
    const bar = chip?.closest<HTMLElement>(".game-header");
    if (!measured || !chip || !bar) return;
    const measure = () => setFullFits(fullRoundFits(bar, chip));
    measure();
    // The bar's width (a turned phone, a resized window), and what is on it:
    // a notice or the Away chip arriving, a countdown's digits, a new round.
    const resizes = new ResizeObserver(measure);
    resizes.observe(bar);
    const changes = new MutationObserver(measure);
    changes.observe(bar, { childList: true, subtree: true, characterData: true });
    // The first measure may run on the fallback font.
    let live = true;
    void document.fonts?.ready.then(() => {
      if (live) measure();
    });
    return () => {
      live = false;
      resizes.disconnect();
      changes.disconnect();
    };
  }, [measured]);

  if (!shown) {
    return null;
  }

  const roundLabel = ui.gameHeaderStatus.roundRoundNumberOfTotalRounds({ roundNumber, totalRounds });

  return (
    <div className="game-header-status">
      <Chip
        ref={chipRef}
        kind="primary"
        className={`game-header-round${isMobile && !fullFits ? " is-short" : ""}`}
      >
        {isMobile ? (
          <>
            {/* Said in full to a screen reader whatever fits on screen. */}
            <span className="visually-hidden">{roundLabel}</span>
            <span className="game-header-round-long" aria-hidden="true">
              {ui.gameHeaderStatus.roundCompact({ roundNumber, totalRounds })}
            </span>
            <span className="game-header-round-short" aria-hidden="true">
              {ui.gameHeaderStatus.roundFraction({ roundNumber, totalRounds })}
            </span>
          </>
        ) : roundLabel}
      </Chip>
      {phase !== "turn_results" && (
        <Timer
          totalSeconds={phaseSeconds}
          startedAt={phaseStartedAt}
          durationSeconds={phaseDurationSeconds}
          paused={clockPaused}
        />
      )}
    </div>
  );
}
