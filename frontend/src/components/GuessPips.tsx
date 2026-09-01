import { Avatar } from "./ui/Avatar";
import { rankGuesses } from "../lib/guessOrder";
import { useGameStore } from "../store/gameStore";
import type { PlayerInfo } from "../types";

/**
 * Who has already guessed, and who is still hunting — the turn's live
 * scoreboard, as one row of avatars.
 *
 * The frozen-eligibility rule (R-GUESS-05) and the drawer bonus (R-SCORE-08)
 * both turn on this, and until now it was invisible during play: the players
 * panel is hidden on a phone while the game is on, so the only way to see it
 * was to open a drawer over the canvas.
 *
 * Tapping the row opens that panel, so the pips double as its affordance.
 */
interface GuessPipsProps {
  onOpenPlayers?: () => void;
}

export function GuessPips({ onOpenPlayers }: GuessPipsProps) {
  const players = useGameStore((state) => state.players);
  const drawerId = useGameStore((state) => state.drawerId);
  const myPlayerId = useGameStore((state) => state.playerId);
  const turnCorrectGuesses = useGameStore((state) => state.turnCorrectGuesses);
  const phase = useGameStore((state) => state.phase);

  if (phase !== "drawing") return null;

  // Spectators never guess, and the drawer is shown by the header rather than
  // as a pip that can never light up.
  const guessers = players.filter(
    (player) => !player.isSpectator && player.playerId !== drawerId,
  );
  if (guessers.length === 0) return null;

  const placeOf = rankGuesses(turnCorrectGuesses);
  const ordered = [...guessers].sort((a, b) => {
    const pa = placeOf[a.playerId] ?? Number.MAX_SAFE_INTEGER;
    const pb = placeOf[b.playerId] ?? Number.MAX_SAFE_INTEGER;
    return pa - pb;
  });
  const got = ordered.filter((player) => placeOf[player.playerId] != null).length;

  const summary = `${got} of ${guessers.length} guessed`;
  const label = onOpenPlayers ? `${summary}. Open players and scores.` : summary;

  const content = (
    <>
      <span className="guess-pip-row">
        {ordered.map((player) => (
          <GuessPip
            key={player.playerId}
            player={player}
            place={placeOf[player.playerId]}
            isMe={player.playerId === myPlayerId}
          />
        ))}
      </span>
      <span className="guess-pip-summary" aria-hidden="true">
        {summary}
      </span>
    </>
  );

  if (!onOpenPlayers) {
    return (
      <div className="guess-pips" data-testid="guess-pips" aria-label={label} role="group">
        {content}
      </div>
    );
  }

  return (
    <button
      type="button"
      className="guess-pips"
      data-testid="guess-pips"
      onClick={onOpenPlayers}
      aria-label={label}
    >
      {content}
    </button>
  );
}

function GuessPip({
  player,
  place,
  isMe,
}: {
  player: PlayerInfo;
  place: number | undefined;
  isMe: boolean;
}) {
  const got = place != null;
  return (
    <span
      className={`guess-pip${got ? " has-guessed" : ""}${isMe ? " is-me" : ""}`}
      title={got ? `${player.nickname} guessed it` : `${player.nickname} is still guessing`}
      data-testid={got ? "guess-pip-correct" : "guess-pip-waiting"}
    >
      <Avatar
        name={player.nickname}
        nameColor={player.nameColor}
        isAnonymous={player.isAnonymous}
        size={26}
      />
      {got && (
        <span className="guess-pip-place" aria-hidden="true">
          {place}
        </span>
      )}
    </span>
  );
}
