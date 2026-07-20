import type { PlayerInfo } from "../types";

interface PlayerListProps {
  players: PlayerInfo[];
  drawerToken: string | null;
}

export function PlayerList({ players, drawerToken }: PlayerListProps) {
  const sorted = [...players].sort((a, b) => b.score - a.score);
  return (
    <ul className="player-list">
      {sorted.map((p) => (
        <li key={p.token} className={`player-row${p.connected ? "" : " disconnected"}`}>
          <span className="player-name">
            {p.token === drawerToken ? "\u270F\uFE0F " : ""}
            {p.nickname}
            {p.isHost ? " \u2605" : ""}
            {!p.connected ? " (disconnected)" : ""}
          </span>
          <span className="player-score">{p.score}</span>
        </li>
      ))}
    </ul>
  );
}
