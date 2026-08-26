import { useMediaQuery } from "../hooks/useMediaQuery";
import { Chip } from "./ui/Chip";
import { Timer } from "./Timer";
import { useGameStore } from "../store/gameStore";

/**
 * The header's center slot during play: round chip + countdown ring. Its own
 * component so the phase/round subscriptions re-render this slot, not the
 * whole room chrome. On mobile the gameplay column carries a compact
 * round/timer line instead (the header hides while guessing).
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

  if (isMobile || roomState !== "playing" || phase === "idle" || phase === "game_end") {
    return null;
  }

  return (
    <div className="game-header-status">
      <Chip kind="primary">Round {roundNumber} of {totalRounds}</Chip>
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
