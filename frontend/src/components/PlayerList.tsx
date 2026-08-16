import type { ModerationState, PlayerInfo } from "../types";
import { socket } from "../lib/socket";
import { canCastModerationVote, eligibleModerationVotes } from "../lib/moderation";

interface PlayerListProps {
  players: PlayerInfo[];
  drawerId: string | null;
  myPlayerId?: string | null;
  showScores?: boolean;
  variant?: "waiting" | "playing" | "game-end";
  allowVoting?: boolean;
  moderation: ModerationState;
}

const PLACEMENT_MEDALS = ["🥇", "🥈", "🥉"];

export function PlayerList({
  players,
  drawerId,
  myPlayerId,
  showScores = true,
  variant = "playing",
  allowVoting = true,
  moderation,
}: PlayerListProps) {
  const sorted = showScores ? [...players].sort((a, b) => b.score - a.score) : players;
  const currentPlayerCanVote = canCastModerationVote(moderation, myPlayerId);

  return (
    <ul className="player-list">
      {sorted.map((p, index) => {
        const isMe = p.playerId === myPlayerId;
        const isDrawer = p.playerId === drawerId;
        const canModerate = Boolean(
          allowVoting && currentPlayerCanVote && !isMe && p.connected,
        );
        const requiredVotes = moderation.requiredVotes;
        const kickVotes = eligibleModerationVotes(moderation, p.kickVotes);
        const afkVotes = eligibleModerationVotes(moderation, p.afkVotes);
        const hasVotedKick = myPlayerId ? kickVotes.includes(myPlayerId) : false;
        const hasVotedAfk = myPlayerId ? afkVotes.includes(myPlayerId) : false;
        const showAfkChip = canModerate ? !p.isAfk : afkVotes.length > 0;
        const showKickChip = canModerate || kickVotes.length > 0;
        const showVoteRow = showAfkChip || showKickChip;
        const rowClass = [
          "player-row",
          isMe ? "is-self" : "",
          p.connected ? "" : "disconnected",
          p.isAfk ? "is-afk" : "",
          showScores ? "has-scores" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <li key={p.playerId} className={rowClass}>
            <PlayerRole
              variant={variant}
              index={index}
              isDrawer={isDrawer}
              isHost={p.isHost}
            />
            <span className="player-name">
              <span className="colored-player-name" style={{ color: p.nameColor }}>
                {p.nickname}
              </span>
              {isMe && <span className="visually-hidden">(you)</span>}
              {p.isAfk && <span className="visually-hidden">AFK</span>}
              {!p.connected && <span className="visually-hidden">Disconnected</span>}
            </span>
            {showScores && <span className="player-score">{p.score}</span>}
            {showVoteRow && (
              <div className="player-vote-row">
                {showAfkChip && (
                  <VoteChip
                    action="afk"
                    nickname={p.nickname}
                    count={afkVotes.length}
                    required={requiredVotes}
                    hasVoted={hasVotedAfk}
                    readOnly={!canModerate}
                    onVote={() => votePlayer(p.playerId, "afk")}
                  />
                )}
                {showKickChip && (
                  <VoteChip
                    action="kick"
                    nickname={p.nickname}
                    count={kickVotes.length}
                    required={requiredVotes}
                    hasVoted={hasVotedKick}
                    readOnly={!canModerate}
                    onVote={() => votePlayer(p.playerId, "kick")}
                  />
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function votePlayer(targetPlayerId: string, action: "kick" | "afk") {
  socket.emit("vote_player", { targetPlayerId, action });
}

function PlayerRole({
  variant,
  index,
  isDrawer,
  isHost,
}: {
  variant: "waiting" | "playing" | "game-end";
  index: number;
  isDrawer: boolean;
  isHost: boolean;
}) {
  if (variant === "game-end") {
    return (
      <span className="player-role" aria-hidden="true">
        {index < 3 ? PLACEMENT_MEDALS[index] : `#${index + 1}`}
      </span>
    );
  }

  if (isDrawer) {
    return (
      <span
        className="player-role"
        aria-label={isHost ? "Drawing, host" : "Drawing"}
        title={isHost ? "Drawing, host" : "Drawing"}
      >
        {"\u270F\uFE0F"}
      </span>
    );
  }

  if (isHost) {
    return (
      <span className="player-role" aria-label="Host" title="Host">
        <HostCrownIcon />
      </span>
    );
  }

  return <span className="player-role" aria-hidden="true" />;
}

function HostCrownIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path
        fill="currentColor"
        d="M2.2 12.5h11.6l-.7-7.2-3.1 2.4L8 4.2 6 7.7 2.9 5.3l-.7 7.2Zm-.4 1.3c-.5 0-.8-.5-.7-1l.8-8.2c.1-.7 1-.9 1.5-.4L5.7 6l1.6-2.8c.3-.6 1.1-.6 1.4 0L10.3 6l2.3-1.8c.5-.5 1.4-.3 1.5.4l.8 8.2c.1.5-.2 1-.7 1H1.8Z"
      />
    </svg>
  );
}

function VoteChip({
  action,
  nickname,
  count,
  required,
  hasVoted,
  readOnly,
  onVote,
}: {
  action: "afk" | "kick";
  nickname: string;
  count: number;
  required: number;
  hasVoted: boolean;
  readOnly: boolean;
  onVote: () => void;
}) {
  const kind = action === "afk" ? "AFK" : "Kick";
  const className = [
    "player-vote-chip",
    `player-vote-chip-${action}`,
    hasVoted ? "is-cast" : "",
    count === 0 ? "is-ghost" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const label = readOnly
    ? `${kind} votes for ${nickname}, ${count} of ${required}`
    : hasVoted
      ? `Undo ${kind} vote for ${nickname}, ${count} of ${required}`
      : `Vote ${kind} for ${nickname}, ${count} of ${required}`;
  const body = count > 0 ? `${kind} ${count}/${required}` : kind;

  if (readOnly) {
    return (
      <span className={className} aria-label={label}>
        {body}
      </span>
    );
  }

  return (
    <button type="button" className={className} aria-label={label} onClick={onVote}>
      {body}
    </button>
  );
}
