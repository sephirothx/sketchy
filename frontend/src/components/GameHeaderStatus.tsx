import { Chip } from "./ui/Chip";
import { Timer } from "./Timer";
import { useGameStore } from "../store/gameStore";
import { TrophyIcon, UsersIcon } from "./icons";

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
  const roomState = useGameStore((s) => s.roomState);
  const phase = useGameStore((s) => s.phase);
  const roundNumber = useGameStore((s) => s.roundNumber);
  const totalRounds = useGameStore((s) => s.totalRounds);
  const phaseSeconds = useGameStore((s) => s.phaseSeconds);
  const phaseStartedAt = useGameStore((s) => s.phaseStartedAt);
  const phaseDurationSeconds = useGameStore((s) => s.phaseDurationSeconds);
  const players = useGameStore((s) => s.players);
  const maxPlayers = useGameStore((s) => s.maxPlayers);

  const seated = players.filter((player) => !player.isSpectator).length;

  // The room's phase, in the bar's centre slot, in every state of the room:
  // who is being waited for, then the round and the clock, then the end.
  if (roomState !== "playing" || phase === "idle") {
    return (
      <div className="game-header-status">
        <Chip kind="success">
          <UsersIcon size={12} />
          {`Waiting · ${seated} of ${maxPlayers}`}
        </Chip>
      </div>
    );
  }
  if (phase === "game_end") {
    return (
      <div className="game-header-status">
        <Chip kind="warm">
          <TrophyIcon size={12} />
          Game over
        </Chip>
      </div>
    );
  }

  return (
    <div className="game-header-status">
      <Chip kind="primary">
        {`Round ${roundNumber} of ${totalRounds}`}
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
