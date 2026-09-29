import type { PlayerInfo, RestartVoteState } from "../types";
import { ui } from "../content/ui/index.ts";

export type RestartVoter = Pick<
  PlayerInfo,
  "playerId" | "connected" | "isAfk" | "isSpectator"
>;

export function restartVoteCounts(vote: RestartVoteState) {
  const eligible = new Set(vote.eligibleVoterIds);
  const yes = vote.yesVoterIds.filter((playerId) => eligible.has(playerId)).length;
  const no = vote.noVoterIds.filter((playerId) => eligible.has(playerId)).length;
  return {
    yes,
    no,
    pending: Math.max(0, eligible.size - yes - no),
    total: eligible.size,
  };
}

export function canCastRestartVote(
  vote: RestartVoteState,
  player: RestartVoter | undefined,
) {
  return Boolean(
    vote.status === "voting"
    && player
    && player.connected
    && !player.isAfk
    && !player.isSpectator
    && vote.eligibleVoterIds.includes(player.playerId),
  );
}

export function secondsUntil(timestamp: number | null, now = Date.now()) {
  if (!timestamp) return 0;
  return Math.max(0, Math.ceil((timestamp - now) / 1000));
}

/** What this seat has voted, if anything. */
export function myRestartVote(vote: RestartVoteState, player: RestartVoter | undefined): boolean | null {
  if (!player) return null;
  if (vote.yesVoterIds.includes(player.playerId)) return true;
  if (vote.noVoterIds.includes(player.playerId)) return false;
  return null;
}

/** The chip's sentence, which is also its accessible name. */
export function restartVoteSentence(vote: RestartVoteState, seconds: number): string {
  return vote.status === "approved"
    ? ui.restartVoteBanner.restartingIn({ seconds })
    : ui.restartVoteBanner.proposerNicknameProposedRestartingRemainingS({
        proposerNickname: vote.proposerNickname,
        remaining: seconds,
      });
}
