import { useEffect, useState } from "react";
import {
  canCastRestartVote,
  myRestartVote,
  restartVoteCounts,
  restartVoteSentence,
  secondsUntil,
} from "../lib/restartVote";
import type { RestartVoter } from "../lib/restartVote";
import type { RestartVoteState } from "../types";
import { ui } from "../content/ui/index.ts";

/** Seconds left on the vote - or, once it passed, until the restart. */
function useRestartVoteSeconds(vote: RestartVoteState): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(interval);
  }, []);
  return secondsUntil(vote.status === "approved" ? vote.restartAt : vote.expiresAt, now);
}

/** The chip's countdown, ticking on its own so the rest of the bar does not. */
export function RestartVoteChipBody({ vote }: { vote: RestartVoteState }) {
  const seconds = useRestartVoteSeconds(vote);
  return (
    <>
      {/* The word and the seconds are what the bar shows; a screen reader
          gets the sentence instead, which says both. */}
      <span className="room-notice-chip-label" aria-hidden="true">
        {vote.status === "approved" ? ui.roomNoticeChips.restarting : ui.roomNoticeChips.restartVote}
      </span>
      <span className="room-notice-chip-seconds" aria-hidden="true">
        {ui.roomNoticeChips.serverUpdateSeconds({ seconds })}
      </span>
      <span className="visually-hidden">{restartVoteSentence(vote, seconds)}</span>
    </>
  );
}

/**
 * A restart vote, as a room-bar chip's popover rather than a banner (#1266).
 *
 * The banner sat in the page flow above the room, so proposing a vote moved
 * the stage: the drawer's canvas jumped 76px mid-stroke, and on a phone in a
 * Wheel of Fortune room the guesser's field went below the fold of a page
 * that does not scroll, for the vote's whole 20 seconds. The bar is where the
 * room's other mid-game notices already live, for that reason (R-UX-07). The
 * tally is said once, in words, and the answers are the design system's
 * buttons.
 */
export function RestartVotePopover({
  id,
  vote,
  player,
  busy,
  onVote,
}: {
  id: string;
  vote: RestartVoteState;
  player: RestartVoter | undefined;
  busy: boolean;
  onVote: (vote: boolean) => void;
}) {
  const seconds = useRestartVoteSeconds(vote);
  const counts = restartVoteCounts(vote);
  const eligible = canCastRestartVote(vote, player);
  const mine = myRestartVote(vote, player);
  return (
    <div
      id={id}
      className={`room-notice-popover restart-vote-popover${vote.status === "approved" ? " is-approved" : ""}`}
      data-notice="restart-vote"
      data-testid="restart-vote"
    >
      <p>
        <strong>
          {vote.status === "approved" ? ui.restartVoteBanner.restartApproved : restartVoteSentence(vote, seconds)}
        </strong>
      </p>
      <p className="restart-vote-tally">
        {vote.status === "approved"
          ? `${ui.restartVoteBanner.theCurrentGameIsRestarting} ${restartVoteSentence(vote, seconds)}.`
          : ui.restartVoteBanner.yesYesNoNoPending({
              yes: counts.yes,
              no: counts.no,
              pending: counts.pending,
              requiredVotes: vote.requiredVotes,
            })}
      </p>
      {vote.status === "voting" && eligible && (
        <div className="room-notice-popover-actions" role="group" aria-label={ui.restartVoteBanner.voteRestartGame}>
          <button
            type="button"
            className={`btn btn-compact ${mine === true ? "btn-primary" : "btn-secondary"}`}
            aria-pressed={mine === true}
            disabled={busy}
            onClick={() => onVote(true)}
          >
            {ui.restartVoteBanner.restart}
          </button>
          <button
            type="button"
            className={`btn btn-compact ${mine === false ? "btn-primary" : "btn-secondary"}`}
            aria-pressed={mine === false}
            disabled={busy}
            onClick={() => onVote(false)}
          >
            {ui.restartVoteBanner.keepPlaying}
          </button>
        </div>
      )}
      {vote.status === "voting" && !eligible && (
        <p className="restart-vote-note">{ui.restartVoteBanner.onlyEligiblePlayersPresentWhenVote}</p>
      )}
    </div>
  );
}
