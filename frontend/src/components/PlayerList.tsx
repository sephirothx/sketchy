import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { ModerationState, PlayerInfo } from "../types";
import { emitWithAck, emitTransient } from "../lib/socket";
import { useToast } from "../lib/toast";
import { ReportPlayerDialog } from "./ReportPlayerDialog";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { competitionRanks } from "../lib/standings";
import {
  canAttachDrawing,
  canCastModerationVote,
  eligibleModerationVotes,
} from "../lib/moderation";
import { getFocusableElements, useEscapeLayer, useFocusTrap } from "../hooks/useFocusTrap";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { Avatar } from "./ui/Avatar";
import { CheckIcon, MedalIcon, MoonIcon, PencilIcon } from "./icons";

interface PlayerListProps {
  players: PlayerInfo[];
  drawerId: string | null;
  myPlayerId?: string | null;
  showScores?: boolean;
  variant?: "waiting" | "playing" | "game-end";
  allowVoting?: boolean;
  moderation: ModerationState;
  /** Per-player elapsed seconds for correct guesses this turn. */
  turnCorrectGuesses?: Record<string, number>;
}

function guessTime(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}


function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function fitPlayerNames(list: HTMLElement) {
  for (const cell of list.querySelectorAll<HTMLElement>(".player-name")) {
    const name = cell.querySelector<HTMLElement>(".colored-player-name");
    if (!name) continue;
    name.style.fontSize = "";
    // Nothing visible shares the line since #574 moved "you" and the crown
    // onto the avatar, so the name may have the whole cell.
    const available = cell.clientWidth;
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
  turnCorrectGuesses,
}: PlayerListProps) {
  const sorted = showScores ? [...players].sort((a, b) => b.score - a.score) : players;
  const ranks = competitionRanks(sorted.map((player) => player.score));
  const currentPlayerCanVote = canCastModerationVote(moderation, myPlayerId);
  const [openMenuToken, setOpenMenuToken] = useState<string | null>(null);
  const [reporting, setReporting] = useState<{ playerId: string; nickname: string } | null>(null);
  // A guest has no account for a moderator to follow up with, so the server
  // refuses their report; offering the control would be a dead end.
  const canRequestReport = useAuthStore(
    (state) => Boolean(state.user && !state.user.isAnonymous),
  );
  const iAmAGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  // Read here rather than passed down: the phase decides one thing on this
  // list - whether a report about the drawer can carry the canvas.
  const phase = useGameStore((state) => state.phase);
  const { notify } = useToast();

  /** Friend somebody by their seat, so no account id crosses the wire.

  Answered plainly here rather than silently: unlike the lobby's list, both
  people are in the same room and can see each other, so there is no third
  party to protect by being vague. */
  async function sendFriendRequest(playerId: string, nickname: string) {
    try {
      const answer = await emitWithAck<{
        ok: boolean;
        error?: string;
        status?: string;
      }>("add_friend", { playerId });
      if (!answer?.ok) {
        notify(answer?.error ?? "That request could not be sent.");
        return;
      }
      // Three outcomes worth telling apart, and one that deliberately is not:
      // anything else - already friends, already asked, or a block - reads as
      // "nothing to do", so the answer never becomes a way to test for one.
      if (answer.status === "accepted") {
        notify(`You and ${nickname} are now friends.`);
      } else if (answer.status === "created") {
        notify(`Friend request sent to ${nickname}.`);
      } else {
        notify(`Nothing to do - you have already asked ${nickname}.`);
      }
    } catch {
      notify("That request could not be sent.");
    }
  }
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
        // Unlike a kick vote, this needs no majority and no eligibility: it
        // asks a moderator to look, rather than doing anything to anyone. It
        // stays available for a disconnected player, because leaving is the
        // usual next thing to happen after the behaviour worth reporting.
        const canReport = Boolean(canRequestReport && !isMe);
        // Offered only where it can work: a guest on either side has no
        // durable identity to hold a friendship, and the server refuses one
        // anyway. Guests are the common case in a room, so a control that
        // always failed would be the usual experience of it.
        // Not hidden for somebody who is already a friend, because the room
        // payload has no account ids to match against (R-ROOM-07) and adding
        // per-viewer flags to room state would make it differ per player,
        // which is exactly what R-BLOCK-03 forbids. The server says what the
        // request actually did instead, and the answer says so.
        const canAddFriend = Boolean(
          !isMe && !iAmAGuest && !p.isAnonymous && p.connected,
        );
        const requiredVotes = moderation.requiredVotes;
        const kickVotes = eligibleModerationVotes(moderation, p.kickVotes);
        const afkVotes = eligibleModerationVotes(moderation, p.afkVotes);
        const hasVotedKick = myPlayerId ? kickVotes.includes(myPlayerId) : false;
        const hasVotedAfk = myPlayerId ? afkVotes.includes(myPlayerId) : false;
        const showAfkChip = afkVotes.length > 0 && !p.isAfk;
        const showKickChip = kickVotes.length > 0;
        const showVoteRow = showAfkChip || showKickChip;
        const guessedAt = turnCorrectGuesses?.[p.playerId];
        const rowClass = cx(
          "player-row",
          isMe && "is-self",
          !p.connected && "disconnected",
          p.isAfk && "is-afk",
          isDrawer && "is-drawing",
          guessedAt != null && !isDrawer && "has-guessed",
          showScores && "has-scores",
          canModerate && "is-moderatable",
        );
        const status = isDrawer ? (
          <span className="player-status player-status-drawing">
            <PencilIcon size={12} />
            Drawing
          </span>
        ) : guessedAt != null ? (
          <span className="player-status player-status-guessed">
            <CheckIcon size={12} />
            Got it · <span className="player-status-time">{guessTime(guessedAt)}</span>
          </span>
        ) : p.isAfk ? (
          <span className="player-status player-status-afk">
            <MoonIcon size={12} />
            AFK
          </span>
        ) : null;

        return (
          <li key={p.playerId} className={rowClass}>
            {(canModerate || canReport) && (
              <PlayerModerationMenu
                player={p}
                canVote={canModerate}
                canReport={canReport}
                requiredVotes={requiredVotes}
                kickVotes={kickVotes}
                afkVotes={afkVotes}
                hasVotedKick={hasVotedKick}
                hasVotedAfk={hasVotedAfk}
                isOpen={openMenuToken === p.playerId}
                onOpenChange={(open) => setOpenMenuToken(open ? p.playerId : null)}
                onReport={() =>
                  setReporting({ playerId: p.playerId, nickname: p.nickname })
                }
                onAddFriend={
                  canAddFriend
                    ? () => void sendFriendRequest(p.playerId, p.nickname)
                    : null
                }
              />
            )}
            {variant === "game-end" && <PlacementBadge rank={ranks[index]} />}
            <Avatar
              name={p.nickname}
              nameColor={p.nameColor}
              avatarUrl={p.avatarUrl}
              isAnonymous={p.isAnonymous}
              isHost={p.isHost}
              isSelf={isMe}
              size={38}
            />
            <span className="player-main">
              <span className="player-name">
                <FittedPlayerName
                  nickname={p.nickname}
                  nameColor={p.nameColor}
                  isAnonymous={p.isAnonymous}
                />
                {/* The ring and the crown are on the avatar (#574); these say
                    the same two things where a screen reader reads the name. */}
                {isMe && <span className="visually-hidden">(you)</span>}
                {p.isHost && <span className="visually-hidden">Host</span>}
                {!p.connected && <span className="visually-hidden">Disconnected</span>}
              </span>
              {status}
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
      {/* Rendered here for the state it reads, but portalled to the body: a
          list item is not a place to put a dialog, in the markup or in the
          stacking order. */}
      {reporting && (
        <ReportPlayerDialog
          targetPlayerId={reporting.playerId}
          nickname={reporting.nickname}
          drawingOffered={canAttachDrawing(phase, drawerId, reporting.playerId)}
          onClose={() => setReporting(null)}
        />
      )}
    </ul>
  );
}

function votePlayer(targetPlayerId: string, action: "kick" | "afk") {
  emitTransient("vote_player", { targetPlayerId, action });
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
      className={playerNameClass(isAnonymous)}
      style={playerNameStyle(nameColor, isAnonymous)}
      // Guests are visually distinct, so state it for screen readers too
      // rather than relying on the italics alone.
      title={isAnonymous ? `${nickname} (guest)` : undefined}
    >
      {nickname}
    </span>
  );
}

/* Podium ranks get a colored medal; the rest keep their number. Keeps the
   .player-role-placement class the e2e suite counts. */
function PlacementBadge({ rank }: { rank: number }) {
  const medalColor =
    rank === 1 ? "var(--gold)" : rank === 2 ? "var(--silver)" : rank === 3 ? "var(--bronze)" : null;
  return (
    <span
      className="player-role player-role-placement"
      role="img"
      aria-label={`Rank ${rank}`}
      title={`Rank ${rank}`}
    >
      {medalColor ? (
        <span style={{ color: medalColor, display: "inline-flex" }}>
          <MedalIcon size={16} />
        </span>
      ) : (
        `#${rank}`
      )}
    </span>
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
  canVote,
  canReport,
  requiredVotes,
  kickVotes,
  afkVotes,
  hasVotedKick,
  hasVotedAfk,
  isOpen,
  onOpenChange,
  onReport,
  onAddFriend,
}: {
  player: PlayerInfo;
  /** Kick and AFK need a live seat and an eligible voter; reporting does not,
      so the two are gated separately and the menu opens for either. */
  canVote: boolean;
  canReport: boolean;
  requiredVotes: number;
  kickVotes: string[];
  afkVotes: string[];
  hasVotedKick: boolean;
  hasVotedAfk: boolean;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onReport: () => void;
  onAddFriend: (() => void) | null;
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

  function handleReport() {
    onOpenChange(false);
    onReport();
  }

  function handleAddFriend() {
    onOpenChange(false);
    onAddFriend?.();
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
        title={canVote ? "Vote AFK or kick, or report" : "Report this player"}
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
          {canVote && !player.isAfk && (
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
          {canVote && (
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
          )}
          {onAddFriend && (
            <button
              type="button"
              role="menuitem"
              className="player-vote-action player-vote-friend"
              onClick={handleAddFriend}
            >
              <span className="player-vote-action-kind">Add friend</span>
              {/* The seat is what is named on the wire; the server resolves
                  who is in it, so no account id passes through here. */}
              <span className="player-vote-action-label">Send a request</span>
            </button>
          )}
          {canReport && (
            <button
              type="button"
              role="menuitem"
              className="player-vote-action player-vote-report"
              onClick={handleReport}
            >
              <span className="player-vote-action-kind">Report</span>
              {/* No count: this asks a moderator to look rather than needing a
                  majority, so there is nothing to tally. */}
              <span className="player-vote-action-label">To a moderator</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
