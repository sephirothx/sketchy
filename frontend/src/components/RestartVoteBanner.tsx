import { useEffect, useState } from "react";
import { canCastRestartVote, restartVoteCounts, secondsUntil } from "../lib/restartVote";
import { CheckIcon, XIcon } from "./icons";
import type { RestartVoter } from "../lib/restartVote";
import type { RestartVoteState } from "../types";
import { ui } from "../content/ui/index.ts";

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
                  <span className="restart-approved-check" aria-hidden="true"><CheckIcon size={15} /></span>
                  {ui.restartVoteBanner.restartApproved}
                </>
              )
            : ui.restartVoteBanner.proposerNicknameProposedRestartingRemainingS({ proposerNickname: vote.proposerNickname, remaining })}
        </strong>
        <span>
          {vote.status === "approved"
            ? ui.restartVoteBanner.theCurrentGameIsRestarting
            : ui.restartVoteBanner.yesYesNoNoPending({ yes: counts.yes, no: counts.no, pending: counts.pending, requiredVotes: vote.requiredVotes })}
        </span>
      </div>
      <div
        className="restart-vote-meter"
        role="img"
        aria-label={ui.restartVoteBanner.voteTally(counts)}
      >
        {castVotes.map(({ playerId, vote: castVote }) => (
          <span
            key={playerId}
            className={`restart-vote-tile ${castVote ? "yes" : "no"}`}
            aria-hidden="true"
          >
            {castVote ? <CheckIcon size={12} /> : <XIcon size={12} />}
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
        <div className="restart-approved-countdown" aria-label={ui.restartVoteBanner.restartingIn({ seconds: remaining })}>
          <strong>{remaining}</strong>
          <span>{ui.restartVoteBanner.seconds}</span>
        </div>
      )}
      {vote.status === "voting" && eligible && (
        <div className="restart-vote-actions" aria-label={ui.restartVoteBanner.voteRestartGame}>
          <button
            type="button"
            className={myVote === true ? "selected yes" : "yes"}
            aria-pressed={myVote === true}
            disabled={busy}
            onClick={() => onVote(true)}
          >
            {ui.restartVoteBanner.restart}
          </button>
          <button
            type="button"
            className={myVote === false ? "selected no" : "no"}
            aria-pressed={myVote === false}
            disabled={busy}
            onClick={() => onVote(false)}
          >
            {ui.restartVoteBanner.keepPlaying}
          </button>
        </div>
      )}
      {vote.status === "voting" && !eligible && (
        <span className="restart-vote-spectator-note">
          {ui.restartVoteBanner.onlyEligiblePlayersPresentWhenVote}
        </span>
      )}
    </section>
  );
}
