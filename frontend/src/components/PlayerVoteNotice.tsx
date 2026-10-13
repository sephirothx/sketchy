import { useEffect, useState } from "react";
import type { OpenPlayerVote } from "../lib/playerVotes";
import { ui } from "../content/ui/index.ts";

/** How long a popover that opened by itself holds its answers back. */
const ARMING_MS = 600;

/**
 * A kick or AFK vote, as a room-bar chip's popover (#1422): the question, the
 * tally, and - for a seat that may vote - the ballot and *Not now*.
 *
 * The same place and shape as the restart vote's (#1266), for the same reason:
 * the bar is where a phone sees the room's mid-game questions, and its players
 * list, where these votes used to be the only trace, is folded behind the Room
 * menu. *Not now* sends nothing - a ballot here is a toggle the server counts,
 * and there is no "no" to cast - it only puts the popover away; the chip stays
 * while the vote is open. Its buttons wait while the connection is down, where
 * a ballot could not be counted.
 */
export function PlayerVotePopover({
  id,
  vote,
  arming,
  offline,
  onVote,
  onDismiss,
}: {
  id: string;
  vote: OpenPlayerVote;
  /** Opened by itself: its answers wait a moment, since it can open under a
      finger already on its way to a letter tile or the canvas. */
  arming: boolean;
  offline: boolean;
  onVote: () => void;
  onDismiss: () => void;
}) {
  const [armed, setArmed] = useState(!arming);
  useEffect(() => {
    if (armed) return;
    const timer = window.setTimeout(() => setArmed(true), ARMING_MS);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const question = vote.aboutMe
    ? vote.kind === "kick" ? ui.playerVoteNotice.kickAboutYou : ui.playerVoteNotice.afkAboutYou
    : vote.kind === "kick"
      ? ui.playerVoteNotice.kickQuestion({ nickname: vote.targetNickname })
      : ui.playerVoteNotice.afkQuestion({ nickname: vote.targetNickname });
  const cast = vote.kind === "kick" ? ui.playerVoteNotice.voteKick : ui.playerVoteNotice.voteAfk;
  return (
    <div
      id={id}
      className="room-notice-popover player-vote-popover"
      data-notice={`player-vote:${vote.key}`}
      data-testid="player-vote"
    >
      <p><strong>{question}</strong></p>
      <p className="restart-vote-tally">
        {ui.playerVoteNotice.tally({ count: vote.count, required: vote.required })}
      </p>
      {vote.canVote && (
        <div className="room-notice-popover-actions" role="group" aria-label={question}>
          <button
            type="button"
            className={`btn btn-compact ${vote.mine ? "btn-secondary" : "btn-primary"}`}
            disabled={offline || !armed}
            onClick={onVote}
          >
            {vote.mine ? ui.playerVoteNotice.withdraw : cast}
          </button>
          <button type="button" className="btn btn-secondary btn-compact" onClick={onDismiss}>
            {ui.friendInviteNotice.notNow}
          </button>
        </div>
      )}
      {!vote.canVote && !vote.aboutMe && (
        <p className="restart-vote-note">{ui.playerVoteNotice.onlyPlayersCanVote}</p>
      )}
    </div>
  );
}
