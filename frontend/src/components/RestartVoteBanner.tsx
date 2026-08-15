import { useEffect, useState } from "react";
import { canCastRestartVote, restartVoteCounts, secondsUntil } from "../lib/restartVote";
import type { RestartVoter } from "../lib/restartVote";
import type { RestartVoteState } from "../types";

interface RestartVoteBannerProps {
  vote: RestartVoteState;
  player: RestartVoter | undefined;
  busy: boolean;
  onVote: (vote: boolean) => void;
}

export function RestartVoteBanner({ vote, player, busy, onVote }: RestartVoteBannerProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(interval);
  }, []);

  const counts = restartVoteCounts(vote);
  const eligibleIds = new Set(vote.eligibleVoterIds);
  const castVotes = vote.castVotes.filter(({ playerId }) => eligibleIds.has(playerId));
  const deadline = vote.status === "approved" ? vote.restartAt : vote.expiresAt;
  const remaining = secondsUntil(deadline, now);
  const eligible = canCastRestartVote(vote, player);
  const myVote = player && vote.yesVoterIds.includes(player.playerId)
    ? true
    : player && vote.noVoterIds.includes(player.playerId)
      ? false
      : null;

  return (
    <section
      className={`restart-vote-banner ${vote.status}`}
      role={vote.status === "approved" ? "alert" : "status"}
      aria-live={vote.status === "approved" ? "assertive" : "polite"}
      data-testid="restart-vote-banner"
    >
      <div className="restart-vote-copy">
        <strong>
          {vote.status === "approved"
            ? (
                <>
                  <span className="restart-approved-check" aria-hidden="true">✓</span>
                  Restart approved!
                </>
              )
            : `${vote.proposerNickname} proposed restarting · ${remaining}s`}
        </strong>
        <span>
          {vote.status === "approved"
            ? "The current game is ending. A fresh game is starting now."
            : `${counts.yes} yes · ${counts.no} no · ${counts.pending} pending · ${vote.requiredVotes} needed`}
        </span>
      </div>
      <div
        className="restart-vote-meter"
        role="img"
        aria-label={`${counts.yes} yes, ${counts.no} no, ${counts.pending} pending`}
      >
        {castVotes.map(({ playerId, vote: castVote }) => (
          <span
            key={playerId}
            className={`restart-vote-tile ${castVote ? "yes" : "no"}`}
            aria-hidden="true"
          >
            {castVote ? "✓" : "×"}
          </span>
        ))}
        {Array.from({ length: counts.pending }, (_, index) => (
          <span
            key={`pending-${index}`}
            className="restart-vote-tile pending"
            aria-hidden="true"
          />
        ))}
      </div>
      {vote.status === "approved" && (
        <div className="restart-approved-countdown" aria-label={`Restarting in ${remaining} seconds`}>
          <strong>{remaining}</strong>
          <span>seconds</span>
        </div>
      )}
      {vote.status === "voting" && eligible && (
        <div className="restart-vote-actions" aria-label="Vote to restart the game">
          <button
            type="button"
            className={myVote === true ? "selected yes" : "yes"}
            aria-pressed={myVote === true}
            disabled={busy}
            onClick={() => onVote(true)}
          >
            Restart
          </button>
          <button
            type="button"
            className={myVote === false ? "selected no" : "no"}
            aria-pressed={myVote === false}
            disabled={busy}
            onClick={() => onVote(false)}
          >
            Keep playing
          </button>
        </div>
      )}
      {vote.status === "voting" && !eligible && (
        <span className="restart-vote-observer-note">
          Only eligible players present when the vote started can vote.
        </span>
      )}
    </section>
  );
}
