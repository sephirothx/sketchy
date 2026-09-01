import { useMediaQuery } from "../hooks/useMediaQuery";
import { Chip } from "./ui/Chip";
import { Timer } from "./Timer";
import { useGameStore } from "../store/gameStore";

/**
 * The header's center slot during play: round chip + countdown ring. Its own
 * component so the phase/round subscriptions re-render this slot, not the
 * whole room chrome.
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

  if (roomState !== "playing" || phase === "idle" || phase === "game_end") {
    return null;
  }

  return (
    <div className="game-header-status">
      <Chip kind="primary">
        {isMobile ? `R${roundNumber}/${totalRounds}` : `Round ${roundNumber} of ${totalRounds}`}
      </Chip>
      {phase !== "turn_results" && (
        <Timer
          totalSeconds={phaseSeconds}
          startedAt={phaseStartedAt}
          durationSeconds={phaseDurationSeconds}
        />
      )}
    </div>
  );
}
