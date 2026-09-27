import { useMediaQuery } from "../hooks/useMediaQuery";
import { Chip } from "./ui/Chip";
import { Timer } from "./Timer";
import { useGameStore } from "../store/gameStore";
import { useRoomStage } from "../hooks/useServerNotices";
import { ui } from "../content/ui/index.ts";

/**
 * The header's center slot during play: round chip + countdown ring. Its own
 * component so the phase/round subscriptions re-render this slot, not the
 * whole room chrome.
 *
 * A phone's round reads "Round 2/3", and "2/3" when the bar has no room for
 * the word beside the wordmark, the clock, any notice and the menu - never
 * "R2/3", which read as a code. The word is the first thing on the bar to go,
 * so it never pushes the wordmark or the clock (R-UX-11). Both labels are
 * rendered, and the bar says which shows: it measures itself as a whole
 * (`useRoomBarGiveWay`), since the round is one of several things that give
 * way there, in order.
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

  const shown = !(roomState !== "playing" || phase === "idle" || phase === "game_end");

  if (!shown) {
    return null;
  }

  const roundLabel = ui.gameHeaderStatus.roundRoundNumberOfTotalRounds({ roundNumber, totalRounds });

  return (
    <div className="game-header-status">
      <Chip kind="primary" className="game-header-round">
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
