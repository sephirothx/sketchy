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
 * A phone's round reads "Round 2/3", and "2/3" on a bar too narrow for the
 * word beside the wordmark, the clock and the menu (the rule is a container
 * query on the bar, in game-room.css) - never "R2/3", which read as a code.
 * Both are rendered and CSS picks one, so the choice cannot lag a resize.
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

  if (roomState !== "playing" || phase === "idle" || phase === "game_end") {
    return null;
  }

  const roundLabel = ui.gameHeaderStatus.roundRoundNumberOfTotalRounds({ roundNumber, totalRounds });
  const roundCompact = ui.gameHeaderStatus.roundCompact({ roundNumber, totalRounds });

  return (
    <div className="game-header-status">
      <Chip
        kind="primary"
        className="game-header-round"
        // How long the full label is, clamped to the four lengths the bar's
        // container queries size for (game-room.css): a longer word needs a
        // wider bar before it fits.
        data-round-chars={isMobile ? Math.min(12, Math.max(9, roundCompact.length)) : undefined}
      >
        {isMobile ? (
          <>
            {/* Said in full to a screen reader whatever fits on screen. */}
            <span className="visually-hidden">{roundLabel}</span>
            <span className="game-header-round-long" aria-hidden="true">
              {roundCompact}
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
