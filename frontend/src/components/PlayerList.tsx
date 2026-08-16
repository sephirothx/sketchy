import { useEffect, useId, useRef, useState } from "react";
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

  return (
    <ul className="player-list">
      {sorted.map((p, index) => {
        const isMe = p.playerId === myPlayerId;
        const canModerate = Boolean(
          allowVoting && currentPlayerCanVote && !isMe && p.connected,
        );
        const requiredVotes = moderation.requiredVotes;
        const kickVotes = eligibleModerationVotes(moderation, p.kickVotes);
        const afkVotes = eligibleModerationVotes(moderation, p.afkVotes);
        const hasVotedKick = myPlayerId ? kickVotes.includes(myPlayerId) : false;
        const hasVotedAfk = myPlayerId ? afkVotes.includes(myPlayerId) : false;
        const isMenuOpen = openMenuToken === p.playerId;

        return (
          <li
            key={p.playerId}
            className={`player-row${p.connected ? "" : " disconnected"}`}
          >
            <div className="player-row-main">
              <span className="player-name">
                {variant === "game-end" && (
                  <span className="player-placement">
                    {index < 3 ? ["🥇", "🥈", "🥉"][index] : `#${index + 1}`}
                  </span>
                )}
                {p.playerId === drawerId ? "\u270F\uFE0F " : ""}
                <span className="colored-player-name" style={{ color: p.nameColor }}>
                  {p.nickname}
                </span>
                {isMe ? " (you)" : ""}
              </span>
              <div className="player-row-meta">
                {(p.isHost || p.isAfk || !p.connected) && (
                  <span className="waiting-player-badges">
                    {p.isHost && <em>Host</em>}
                    {p.isAfk && <em className="warning">AFK</em>}
                    {!p.connected && <em className="muted">Disconnected</em>}
                  </span>
                )}
                {(afkVotes.length > 0 || kickVotes.length > 0) && (
                  <span className="player-vote-summary">
                    {afkVotes.length > 0 && (
                      <span
                        className={`player-vote-chip player-vote-chip-afk${hasVotedAfk ? " is-cast" : ""}`}
                        aria-label={`AFK votes ${afkVotes.length} of ${requiredVotes}${hasVotedAfk ? ", including yours" : ""}`}
                      >
                        AFK {afkVotes.length}/{requiredVotes}
                      </span>
                    )}
                    {kickVotes.length > 0 && (
                      <span
                        className={`player-vote-chip player-vote-chip-kick${hasVotedKick ? " is-cast" : ""}`}
                        aria-label={`Kick votes ${kickVotes.length} of ${requiredVotes}${hasVotedKick ? ", including yours" : ""}`}
                      >
                        Kick {kickVotes.length}/{requiredVotes}
                      </span>
                    )}
                  </span>
                )}
                {showScores && <span className="player-score">{p.score}</span>}
                {canModerate && (
                  <PlayerModerationMenu
                    player={p}
                    requiredVotes={requiredVotes}
                    kickVotes={kickVotes}
                    afkVotes={afkVotes}
                    hasVotedKick={hasVotedKick}
                    hasVotedAfk={hasVotedAfk}
                    isOpen={isMenuOpen}
                    onOpenChange={(open) => setOpenMenuToken(open ? p.playerId : null)}
                  />
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
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
    socket.emit("vote_player", { targetPlayerId: player.playerId, action });
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
        onClick={() => onOpenChange(!isOpen)}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="5" r="2" fill="currentColor" />
          <circle cx="12" cy="12" r="2" fill="currentColor" />
          <circle cx="12" cy="19" r="2" fill="currentColor" />
        </svg>
      </button>
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
