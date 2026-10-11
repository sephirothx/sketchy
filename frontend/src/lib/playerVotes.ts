import type { ModerationState, PlayerInfo } from "../types";
import { canCastModerationVote, eligibleModerationVotes } from "./moderation.ts";
import { ui } from "../content/ui/index.ts";

/** A kick or AFK vote somebody has opened on a seat, as this seat sees it. */
export interface OpenPlayerVote {
  /** Stable while the vote is open: the room bar's chip and its popover. */
  key: string;
  kind: "kick" | "afk";
  targetId: string;
  targetNickname: string;
  count: number;
  required: number;
  /** This seat's ballot is among the votes. */
  mine: boolean;
  /** This seat may cast or withdraw a ballot: an eligible voter, and not the
      vote's target. */
  canVote: boolean;
  /** The vote is about this seat. */
  aboutMe: boolean;
}

/**
 * Every kick and AFK vote open in the room, from the players' tallies (#1422).
 *
 * The tallies already reach every seat in the room snapshot; until now only
 * the desktop players list read them, so a phone - whose list is behind the
 * Room menu - never learned that a vote was open, and a vote nobody sees never
 * reaches its strict majority (R-VOTE-02). Counted as the list counts them:
 * only ballots from seats that may still vote, and an AFK vote on a seat that
 * is already AFK is over.
 */
export function openPlayerVotes(
  players: readonly PlayerInfo[],
  moderation: ModerationState,
  myPlayerId: string | null | undefined,
): OpenPlayerVote[] {
  const iMayVote = canCastModerationVote(moderation, myPlayerId);
  const votes: OpenPlayerVote[] = [];
  for (const player of players) {
    for (const kind of ["kick", "afk"] as const) {
      const ballots = eligibleModerationVotes(
        moderation,
        kind === "kick" ? player.kickVotes : player.afkVotes,
      );
      if (ballots.length === 0 || (kind === "afk" && player.isAfk)) continue;
      const aboutMe = player.playerId === myPlayerId;
      votes.push({
        key: `${kind}:${player.playerId}`,
        kind,
        targetId: player.playerId,
        targetNickname: player.nickname,
        count: ballots.length,
        required: moderation.requiredVotes,
        mine: Boolean(myPlayerId && ballots.includes(myPlayerId)),
        canVote: iMayVote && !aboutMe,
        aboutMe,
      });
    }
  }
  return votes;
}

/** The votes still waiting on this seat's ballot. */
export function votesAwaitingMe(votes: readonly OpenPlayerVote[]): OpenPlayerVote[] {
  return votes.filter((vote) => vote.canVote && !vote.mine);
}

/** The chip's words: the kind and the tally, as the players list writes them. */
export function playerVoteChipBody(vote: OpenPlayerVote): string {
  const kind = vote.kind === "kick" ? ui.playerList.voteKindKick : ui.playerList.voteKindAfk;
  return `${kind} ${vote.count}/${vote.required}`;
}

/** The chip's name for a screen reader: the sentence the players list says. */
export function playerVoteChipLabel(vote: OpenPlayerVote): string {
  const tally = {
    kind: vote.kind === "kick" ? ui.playerList.voteKindKick : ui.playerList.voteKindAfk,
    nickname: vote.targetNickname,
    count: vote.count,
    required: vote.required,
  };
  return vote.mine ? ui.playerList.votesForIncludingYours(tally) : ui.playerList.votesFor(tally);
}
