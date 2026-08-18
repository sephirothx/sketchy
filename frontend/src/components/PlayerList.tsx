import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { ModerationState, PlayerInfo } from "../types";
import { socket } from "../lib/socket";
import { canCastModerationVote, eligibleModerationVotes } from "../lib/moderation";
import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";

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

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function fitPlayerNames(list: HTMLElement) {
  for (const cell of list.querySelectorAll<HTMLElement>(".player-name")) {
    const name = cell.querySelector<HTMLElement>(".colored-player-name");
    if (!name) continue;
    name.style.fontSize = "";
    const youMark = cell.querySelector(".player-you-mark");
    const gap = youMark ? parseFloat(getComputedStyle(cell).gap) || 0 : 0;
    const available =
      cell.clientWidth - (youMark instanceof HTMLElement ? youMark.offsetWidth : 0) - gap;
    const range = document.createRange();
    range.selectNodeContents(name);
    const natural = range.getBoundingClientRect().width;
    if (natural > available && available > 0) {
      const current = parseFloat(getComputedStyle(name).fontSize);
      name.style.fontSize = `${(available / natural) * current}px`;
    }
  }
}

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
  const [openMenuToken, setOpenMenuToken] = useState<string | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const nameFitKey = sorted.map((player) => `${player.playerId}:${player.nickname}`).join("\0");

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    fitPlayerNames(list);
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => fitPlayerNames(list));
    });
    observer.observe(list);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [nameFitKey, showScores, myPlayerId]);

  return (
    <ul ref={listRef} className="player-list">
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
        const showAfkChip = afkVotes.length > 0 && !p.isAfk;
        const showKickChip = kickVotes.length > 0;
        const showVoteRow = showAfkChip || showKickChip;
        const rowClass = cx(
          "player-row",
          isMe && "is-self",
          !p.connected && "disconnected",
          p.isAfk && "is-afk",
          showScores && "has-scores",
          canModerate && "is-moderatable",
        );

        return (
          <li key={p.playerId} className={rowClass}>
            {canModerate && (
              <PlayerModerationMenu
                player={p}
                requiredVotes={requiredVotes}
                kickVotes={kickVotes}
                afkVotes={afkVotes}
                hasVotedKick={hasVotedKick}
                hasVotedAfk={hasVotedAfk}
                isOpen={openMenuToken === p.playerId}
                onOpenChange={(open) => setOpenMenuToken(open ? p.playerId : null)}
              />
            )}
            <PlayerRole
              variant={variant}
              index={index}
              isDrawer={isDrawer}
              isHost={p.isHost}
              isAfk={p.isAfk}
            />
            <span className="player-name">
              <FittedPlayerName nickname={p.nickname} nameColor={p.nameColor} isAnonymous={p.isAnonymous} />
              {isMe && <span className="player-you-mark">you</span>}
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
                    onVote={canModerate ? () => votePlayer(p.playerId, "afk") : undefined}
                  />
                )}
                {showKickChip && (
                  <VoteChip
                    action="kick"
                    nickname={p.nickname}
                    count={kickVotes.length}
                    required={requiredVotes}
                    hasVoted={hasVotedKick}
                    onVote={canModerate ? () => votePlayer(p.playerId, "kick") : undefined}
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

function FittedPlayerName({
  nickname,
  nameColor,
  isAnonymous,
}: {
  nickname: string;
  nameColor?: string;
  isAnonymous?: boolean;
}) {
  return (
    <span
      className="colored-player-name"
      style={{
        color: isAnonymous ? "#888888" : nameColor,
        fontStyle: isAnonymous ? "italic" : "normal",
      }}
    >
      {nickname}
    </span>
  );
}

function PlayerRole({
  variant,
  index,
  isDrawer,
  isHost,
  isAfk,
}: {
  variant: "waiting" | "playing" | "game-end";
  index: number;
  isDrawer: boolean;
  isHost: boolean;
  isAfk: boolean;
}) {
  // One icon per row, in this order: drawing, AFK, host. Combined states
  // (host+AFK, drawer+host) are exposed on aria-label/title instead.
  if (variant === "game-end") {
    return (
      <span className="player-role player-role-placement" aria-hidden="true">
        {index < 3 ? PLACEMENT_MEDALS[index] : `#${index + 1}`}
      </span>
    );
  }

  if (isDrawer) {
    const drawingLabel = [isHost ? "host" : null, isAfk ? "AFK" : null]
      .filter(Boolean)
      .join(", ");
    return (
      <span
        className="player-role"
        role="img"
        aria-label={drawingLabel ? `Drawing, ${drawingLabel}` : "Drawing"}
        title={drawingLabel ? `Drawing, ${drawingLabel}` : "Drawing"}
      >
        {"\u270F\uFE0F"}
      </span>
    );
  }

  if (isAfk) {
    return (
      <span className="player-role player-role-afk" role="img" aria-label="AFK" title="AFK">
        zzz
      </span>
    );
  }

  if (isHost) {
    return (
      <span className="player-role" role="img" aria-label="Host" title="Host">
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
  onVote,
}: {
  action: "afk" | "kick";
  nickname: string;
  count: number;
  required: number;
  hasVoted: boolean;
  onVote?: () => void;
}) {
  const kind = action === "afk" ? "AFK" : "Kick";
  const className = cx(
    "player-vote-chip",
    `player-vote-chip-${action}`,
    hasVoted && "is-cast",
  );
  const label = onVote
    ? hasVoted
      ? `Undo ${kind} vote for ${nickname}, ${count} of ${required}`
      : `Vote ${kind} for ${nickname}, ${count} of ${required}`
    : `${kind} votes for ${nickname}, ${count} of ${required}${hasVoted ? ", including yours" : ""}`;
  const body = `${kind} ${count}/${required}`;

  if (!onVote) {
    return (
      <span className={className} role="status" aria-label={label}>
        {body}
      </span>
    );
  }

  return (
    <button
      type="button"
      className={className}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onVote();
      }}
    >
      {body}
    </button>
  );
}

function PlayerModerationMenu({
  player,
  requiredVotes,
  kickVotes,
  afkVotes,
  hasVotedKick,
  hasVotedAfk,
  isOpen,
  onOpenChange,
}: {
  player: PlayerInfo;
  requiredVotes: number;
  kickVotes: string[];
  afkVotes: string[];
  hasVotedKick: boolean;
  hasVotedAfk: boolean;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const hasSelfVote = hasVotedKick || hasVotedAfk;

  useEscapeLayer(isOpen, () => onOpenChange(false));
  useFocusTrap(menuRef, { active: isOpen });

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        onOpenChange(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onOpenChange]);

  function handleVote(action: "kick" | "afk") {
    votePlayer(player.playerId, action);
    onOpenChange(false);
    triggerRef.current?.focus();
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const items = menuRef.current ? getFocusableElements(menuRef.current) : [];
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      items[(currentIndex + 1) % items.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      items[(currentIndex - 1 + items.length) % items.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      items[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      items[items.length - 1]?.focus();
    }
  }

  return (
    <div ref={rootRef} className="player-moderation">
      <button
        ref={triggerRef}
        type="button"
        className={`player-moderation-trigger${hasSelfVote ? " has-self-vote" : ""}`}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={menuId}
        aria-label={`Moderation for ${player.nickname}`}
        title="Vote AFK or kick"
        onClick={() => onOpenChange(!isOpen)}
      />
      {isOpen && (
        <div
          ref={menuRef}
          id={menuId}
          className="player-vote-menu"
          role="menu"
          aria-label={`Moderation actions for ${player.nickname}`}
          tabIndex={-1}
          onKeyDown={handleMenuKeyDown}
        >
          {!player.isAfk && (
            <button
              type="button"
              role="menuitem"
              className={`player-vote-action player-vote-afk${hasVotedAfk ? " is-cast" : ""}`}
              onClick={() => handleVote("afk")}
            >
              <span className="player-vote-action-kind">AFK</span>
              <span className="player-vote-action-label">
                {hasVotedAfk ? "Undo vote" : "Vote"}
              </span>
              <span className="player-vote-action-count">
                {afkVotes.length}/{requiredVotes}
              </span>
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className={`player-vote-action player-vote-kick${hasVotedKick ? " is-cast" : ""}`}
            onClick={() => handleVote("kick")}
          >
            <span className="player-vote-action-kind">Kick</span>
            <span className="player-vote-action-label">
              {hasVotedKick ? "Undo vote" : "Vote"}
            </span>
            <span className="player-vote-action-count">
              {kickVotes.length}/{requiredVotes}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
