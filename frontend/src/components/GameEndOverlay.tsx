import { useEffect, useState } from "react";
import { useAuthStore } from "../store/authStore";
import { AuthDialog, type AuthMode } from "./AccountMenu";
import type { ScoreEntry, ScoringMode } from "../types";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { competitionRanks, crownOutcome } from "../lib/standings";
import { Avatar } from "./ui/Avatar";
import { SectionLabel } from "./ui/Card";
import { BrushIcon, CrownIcon, TimerRing, TrophyIcon } from "./icons";

interface GameEndOverlayProps {
  scores: ScoreEntry[];
  myPlayerId: string | null;
  scoringMode: ScoringMode;
  onContinue: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
  highlightCount: number;
  onViewHighlights: () => void;
}

const DISPLAY_SECONDS = 10;

const PODIUM_COLORS = ["var(--gold)", "var(--silver)", "var(--bronze)"];
const PODIUM_HEIGHTS = [104, 74, 56];

function ordinal(place: number): string {
  const tail = place % 100;
  if (tail >= 11 && tail <= 13) return `${place}th`;
  const last = place % 10;
  return `${place}${last === 1 ? "st" : last === 2 ? "nd" : last === 3 ? "rd" : "th"}`;
}

function ConfettiDots() {
  return (
    <svg className="game-end-confetti" width="360" height="44" viewBox="0 0 360 44" fill="none" aria-hidden="true">
      <circle cx="24" cy="26" r="4" style={{ fill: "var(--warm)" }} />
      <rect x="70" y="10" width="8" height="8" rx="2" style={{ fill: "var(--primary)" }} transform="rotate(18 74 14)" />
      <circle cx="126" cy="14" r="3.5" style={{ fill: "var(--success)" }} />
      <rect x="168" y="22" width="9" height="9" rx="2" style={{ fill: "var(--warm)" }} transform="rotate(-14 172 26)" />
      <circle cx="228" cy="10" r="4" style={{ fill: "var(--primary)" }} />
      <rect x="272" y="16" width="8" height="8" rx="2" style={{ fill: "var(--success)" }} transform="rotate(24 276 20)" />
      <circle cx="330" cy="24" r="3.5" style={{ fill: "var(--warm)" }} />
    </svg>
  );
}

export function GameEndOverlay({
  scores,
  myPlayerId,
  scoringMode,
  onContinue,
  drawingCount,
  onViewDrawings,
  highlightCount,
  onViewHighlights,
}: GameEndOverlayProps) {
  const [remaining, setRemaining] = useState(DISPLAY_SECONDS);
  // "Stay here": the room is not going anywhere, and neither is the player.
  const [hold, setHold] = useState(false);
  const user = useAuthStore((state) => state.user);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  // The strongest moment to ask: their result is on screen and there is now
  // something to lose.
  const isUnclaimedGuest = Boolean(user?.isAnonymous && user.displayName);

  useEffect(() => {
    // Hold the countdown while the claim form is open, or the overlay would
    // disappear from under someone mid-way through typing a password.
    if (authMode || hold) return;
    const timeout = setTimeout(onContinue, DISPLAY_SECONDS * 1000);
    const interval = setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [onContinue, authMode, hold]);

  // Places, not row numbers: two players level on points tied for the same one.
  const ranks = competitionRanks(scores.map((score) => score.score));
  const myIndex = scores.findIndex((score) => score.playerId === myPlayerId);
  const placement = myIndex >= 0 ? ranks[myIndex] : 1;
  const myScore = myIndex >= 0 ? scores[myIndex].score : null;
  // A shared first has no single winner to crown, and saying otherwise would
  // contradict the two golds in the standings directly below.
  const winners = scores.filter((_score, index) => ranks[index] === 1);
  const crown = crownOutcome(winners.length);
  const podium = scores.slice(0, 3);
  // Silver · gold · bronze, the classic arrangement.
  const podiumOrder = podium.length === 3 ? [1, 0, 2] : podium.length === 2 ? [1, 0] : [0];
  const rest = scores.slice(3);
  const countdownVisible = !authMode && !hold;

  return <main className="game-end-overlay" aria-labelledby="game-end-title" aria-live="polite" data-testid="game-end-overlay">
    <section className="game-end-podium">
      <ConfettiDots />
      <SectionLabel>Game over</SectionLabel>
      <h1 id="game-end-title">
        {scoringMode !== "none" && (
          <span className="game-end-crown" aria-hidden="true">
            <CrownIcon size={26} />
          </span>
        )}
        {scoringMode === "none"
          ? "A great game of drawing"
          : crown === "room"
            ? "The room takes the crown!"
            : crown === "many"
              ? `${winners.length} players share the crown!`
              : <>
                  {winners.map((winner, index) => (
                    <span key={winner.playerId}>
                      {index > 0 ? (index === winners.length - 1 ? " and " : ", ") : ""}
                      <span
                        className={playerNameClass(winner.isAnonymous)}
                        style={playerNameStyle(winner.nameColor, winner.isAnonymous)}
                      >
                        {winner.nickname}
                      </span>
                    </span>
                  ))}
                  {crown === "one" ? " takes the crown!" : " share the crown!"}
                </>}
      </h1>
      {scoringMode !== "none" ? (
        <>
          {myScore != null && (
            <p className="game-end-placement">
              You finished <strong>{ordinal(Math.max(1, placement))}</strong> with {myScore} points.
            </p>
          )}
          <div className="game-end-podium-row">
            {podiumOrder.map((scoreIndex) => {
              const entry = podium[scoreIndex];
              const place = ranks[scoreIndex];
              const color = PODIUM_COLORS[Math.min(place, 3) - 1] ?? "var(--faint)";
              const height = PODIUM_HEIGHTS[Math.min(place, 3) - 1] ?? 48;
              return (
                <div key={entry.playerId} className="game-end-podium-col">
                  <Avatar
                    name={entry.nickname}
                    nameColor={entry.nameColor}
                    avatarUrl={entry.avatarUrl}
                    isAnonymous={entry.isAnonymous}
                    size={place === 1 ? 52 : 42}
                  />
                  <span className="game-end-podium-name">
                    <span
                      className={playerNameClass(entry.isAnonymous)}
                      style={playerNameStyle(entry.nameColor, entry.isAnonymous)}
                    >
                      {entry.nickname}
                    </span>
                    {entry.playerId === myPlayerId && <span className="game-end-you">you</span>}
                  </span>
                  <div className="game-end-podium-block" style={{ height, background: color }}>
                    <span className="game-end-podium-place">{place}</span>
                    <span className="game-end-podium-score">{entry.score}</span>
                  </div>
                </div>
              );
            })}
          </div>
          {rest.length > 0 && (
            <ol className="game-end-standings">
              {rest.map((score, index) => (
                <li key={score.playerId} className={score.playerId === myPlayerId ? "is-you" : ""}>
                  <span className="game-end-standing-rank">#{ranks[index + 3]}</span>
                  <Avatar
                    name={score.nickname}
                    nameColor={score.nameColor}
                    avatarUrl={score.avatarUrl}
                    isAnonymous={score.isAnonymous}
                    size={26}
                  />
                  <span className="game-end-standing-name">
                    <span className={playerNameClass(score.isAnonymous)} style={playerNameStyle(score.nameColor, score.isAnonymous)}>{score.nickname}</span>
                    {score.playerId === myPlayerId ? <span className="game-end-you">you</span> : null}
                  </span>
                  <strong>{score.score}</strong>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : (
        <p className="game-end-no-score">No scores this time—just a room full of sketches and guesses.</p>
      )}
      {isUnclaimedGuest && (
        <aside className="game-end-claim">
          {/* One line. Three lines of explanation cost more of this screen
              than the podium did, for a nudge nobody came here to read. */}
          <p className="game-end-claim-copy">
            Keep <strong>{user!.displayName}</strong> as your username
          </p>
          <button
            type="button"
            className="game-end-claim-action"
            onClick={() => setAuthMode("claim")}
          >
            Create account
          </button>
        </aside>
      )}

      <div className="game-end-actions">
        {highlightCount > 0 && (
          <button type="button" className="btn btn-secondary" onClick={onViewHighlights}>
            <TrophyIcon size={15} />
            Highlights
          </button>
        )}
        {drawingCount > 0 && (
          <button type="button" className="btn btn-secondary" onClick={onViewDrawings}>
            <BrushIcon size={15} />
            Drawings
          </button>
        )}
        <button
          type="button"
          className="game-end-continue"
          aria-label={countdownVisible
            ? `Continue to waiting room, ${remaining} seconds left`
            : "Continue to waiting room"}
          onClick={onContinue}
        >
          {countdownVisible && (
            <TimerRing
              seconds={remaining}
              fraction={remaining / DISPLAY_SECONDS}
              color="#fff"
              size={28}
              track="rgba(255, 255, 255, 0.35)"
            />
          )}
          Continue
        </button>
      </div>
      {!hold && (
        <p className="game-end-stay">
          <button type="button" className="game-end-stay-link" onClick={() => setHold(true)}>
            Stay here
          </button>
        </p>
      )}
    </section>
    {authMode && (
      <AuthDialog
        mode={authMode}
        suggestedUsername={user?.displayName ?? ""}
        onClose={() => setAuthMode(null)}
        onSwitchMode={setAuthMode}
        onSubmit={authMode === "login" ? login : register}
      />
    )}
  </main>;
}
