import { useState, useEffect, useRef } from "react";
import type { PlayerInfo } from "../types";
import { socket } from "../lib/socket";

interface PlayerListProps {
  players: PlayerInfo[];
  drawerId: string | null;
  myPlayerId?: string | null;
  showScores?: boolean;
  variant?: "waiting" | "playing" | "game-end";
  allowVoting?: boolean;
  votingPopulation?: PlayerInfo[];
}

export function PlayerList({
  players,
  drawerId,
  myPlayerId,
  showScores = true,
  variant = "playing",
  allowVoting = true,
  votingPopulation = players,
}: PlayerListProps) {
  const sorted = showScores ? [...players].sort((a, b) => b.score - a.score) : players;
  const connectedPlayers = votingPopulation.filter((p) => p.connected);
  const [openMenuToken, setOpenMenuToken] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuToken(null);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleVote(targetPlayerId: string, action: "kick" | "afk") {
    socket.emit("vote_player", { targetPlayerId, action });
    setOpenMenuToken(null);
  }

  return (
    <ul className="player-list">
      {sorted.map((p, index) => {
        const isMe = p.playerId === myPlayerId;
        const requiredVotes = Math.floor(connectedPlayers.length / 2) + 1;
        const kickVotes = (p.kickVotes || []).filter((v) => connectedPlayers.some((cp) => cp.playerId === v));
        const afkVotes = (p.afkVotes || []).filter((v) => connectedPlayers.some((cp) => cp.playerId === v));
        const hasVotedKick = myPlayerId ? kickVotes.includes(myPlayerId) : false;
        const hasVotedAfk = myPlayerId ? afkVotes.includes(myPlayerId) : false;
        const totalActiveVotes = Math.max(kickVotes.length, afkVotes.length);
        const isMenuOpen = openMenuToken === p.playerId;

        return (
          <li
            key={p.playerId}
            className={`player-row${p.connected ? "" : " disconnected"}${allowVoting && !isMe && p.connected ? " clickable" : ""}`}
            style={{
              position: "relative",
            }}
            title={allowVoting && !isMe && p.connected ? "Click to vote AFK or Kick player" : undefined}
            onClick={() => {
              if (allowVoting && !isMe && p.connected) {
                setOpenMenuToken(isMenuOpen ? null : p.playerId);
              }
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <span className="player-name">
                {variant === "game-end" && <span className="player-placement">{index < 3 ? ["🥇", "🥈", "🥉"][index] : `#${index + 1}`}</span>}
                {p.playerId === drawerId ? "\u270F\uFE0F " : ""}
                <span className="colored-player-name" style={{ color: p.nameColor }}>
                  {p.nickname}
                </span>
                {isMe ? " (you)" : ""}
                {totalActiveVotes > 0 && (
                  <span
                    style={{
                      fontSize: "0.75rem",
                      marginLeft: "0.4rem",
                      padding: "0.1rem 0.35rem",
                      borderRadius: "4px",
                      background: "rgba(239, 68, 68, 0.2)",
                      color: "#f87171",
                      fontWeight: 600,
                    }}
                    title={`${totalActiveVotes} of ${requiredVotes} votes cast`}
                  >
                    🗳️ {totalActiveVotes}/{requiredVotes}
                  </span>
                )}
              </span>
              <span className="waiting-player-badges">
                {p.isHost && <em>Host</em>}
                {p.isAfk && <em className="warning">AFK</em>}
                {!p.connected && <em className="muted">Disconnected</em>}
              </span>
              {showScores && <span className="player-score">{p.score}</span>}
            </div>

            {allowVoting && isMenuOpen && !isMe && p.connected && (
              <div
                ref={menuRef}
                className="player-vote-menu"
                style={{
                  position: "absolute",
                  right: 0,
                  top: "100%",
                  marginTop: "0.25rem",
                  background: "#1e293b",
                  border: "1px solid rgba(255,255,255,0.2)",
                  borderRadius: "6px",
                  boxShadow: "0 6px 16px rgba(0,0,0,0.5)",
                  padding: "0.4rem",
                  zIndex: 100,
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.3rem",
                  minWidth: "140px",
                }}
                onClick={(e) => e.stopPropagation()}
              >
                {!p.isAfk && (
                  <button
                    style={{
                      fontSize: "0.75rem",
                      padding: "0.3rem 0.5rem",
                      background: hasVotedAfk ? "#f59e0b" : "rgba(255,255,255,0.05)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "4px",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                    onClick={() => handleVote(p.playerId, "afk")}
                  >
                    {hasVotedAfk ? "✓ " : ""}Vote AFK ({afkVotes.length}/{requiredVotes})
                  </button>
                )}
                <button
                  style={{
                    fontSize: "0.75rem",
                    padding: "0.3rem 0.5rem",
                    background: hasVotedKick ? "#ef4444" : "rgba(255,255,255,0.05)",
                    color: "#fff",
                    border: "none",
                    borderRadius: "4px",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                  onClick={() => handleVote(p.playerId, "kick")}
                >
                  {hasVotedKick ? "✓ " : ""}Vote Kick ({kickVotes.length}/{requiredVotes})
                </button>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
