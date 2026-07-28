import type { HintMode, PlayerInfo, ScoreEntry, ScoringMode } from "../types";
import { useState } from "react";
import { WaitingRoomChat } from "./WaitingRoomChat";
import { RoomSettingsEditor } from "./RoomSettingsDialog";
import type { ChatMessage } from "../types";

interface WaitingRoomPanelProps {
  name: string; code: string; isPublic: boolean; maxPlayers: number; rounds: number;
  drawingSeconds: number; customWordCount: number; customWordsOnly: boolean;
  hintMode: HintMode; scoringMode: ScoringMode; spectatorsSeeSolution: boolean;
  hideMaskedPrompt: boolean; players: PlayerInfo[]; myToken: string | null;
  isHost: boolean; finalScores: ScoreEntry[] | null; startBusy: boolean;
  startError: string | null; onStart: () => void; onCopyInvite: () => void;
  messages: ChatMessage[]; onLeave: () => void; onSaveDrawing: () => void; hasDrawing: boolean;
}

function hintLabel(mode: HintMode, hidden: boolean) {
  if (hidden) return "Prompt details hidden";
  return ({ checkpoints: "Timed letter hints", purchase: "Buyable letter hints", wheel: "Wheel-style letter hints", none: "No letter hints" })[mode];
}

export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  const { players, myToken, isHost, finalScores } = props;
  const activePlayers = players.filter((player) => !player.isSpectator);
  const spectators = players.filter((player) => player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const canStart = eligiblePlayers.length >= 2;
  const needsPlayers = Math.max(0, 2 - eligiblePlayers.length);
  const rematch = Boolean(finalScores);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return <main className="waiting-room" data-testid="waiting-room">
    <section className="waiting-room-intro">
      <div>
        <p className="waiting-room-eyebrow">{props.isPublic ? "Public room" : "Private room"}</p>
        <h1>{props.name}</h1>
        <p className="waiting-room-subtitle">{rematch ? "Last game complete. The lobby is ready for a rematch." : "Get everyone ready before the first round."}</p>
      </div>
      <button type="button" className="waiting-invite-button" onClick={props.onCopyInvite}>Invite · {props.code}</button>
    </section>

    <div className="waiting-room-layout">
    <div className="waiting-room-main">
    <div className="waiting-room-grid">
      <section className="waiting-card waiting-roster-card" aria-labelledby="waiting-roster-title">
        <div className="waiting-card-heading"><div><p className="waiting-card-kicker">People in room</p><h2 id="waiting-roster-title">Players ({activePlayers.length}/{props.maxPlayers})</h2></div><span className={`waiting-ready-count ${canStart ? "is-ready" : ""}`}>{eligiblePlayers.length} ready</span></div>
        <ul className="waiting-roster-list">{activePlayers.map((player) => <li key={player.token} className={!player.connected ? "is-disconnected" : ""}><span>{player.nickname}{player.token === myToken ? " (you)" : ""}</span><span className="waiting-player-badges">{player.isHost && <em>Host</em>}{player.isAfk && <em className="warning">AFK</em>}{!player.connected && <em className="muted">Disconnected</em>}</span></li>)}</ul>
        {spectators.length > 0 && <div className="waiting-spectators"><h3>Spectators ({spectators.length})</h3><ul className="waiting-roster-list">{spectators.map((player) => <li key={player.token} className={!player.connected ? "is-disconnected" : ""}><span>{player.nickname}{player.token === myToken ? " (you)" : ""}</span><span className="waiting-player-badges"><em>Spectator</em>{player.isAfk && <em className="warning">AFK</em>}</span></li>)}</ul></div>}
      </section>

      <section className="waiting-card waiting-rules-card" aria-labelledby="waiting-rules-title">
        <p className="waiting-card-kicker">Room rules</p><h2 id="waiting-rules-title">How this game will play</h2>
        <ul className="waiting-rules-list">
          <li>{props.rounds} round{props.rounds === 1 ? "" : "s"} each · {props.drawingSeconds}s to draw</li>
          <li>{props.scoringMode === "default" ? "Points for fast, correct guesses" : "No scorekeeping"}</li>
          <li>{hintLabel(props.hintMode, props.hideMaskedPrompt)}</li>
          <li>{props.customWordsOnly ? `Custom words only (${props.customWordCount})` : props.customWordCount ? `${props.customWordCount} custom words included` : "Built-in word list"}</li>
          <li>{props.spectatorsSeeSolution ? "Spectators can see the solution" : "Spectators guess along"}</li>
        </ul>
      </section>
    </div>

    <section className="waiting-card waiting-start-card" aria-live="polite">
      {isHost ? <><div><p className="waiting-card-kicker">Host controls</p><h2>{rematch ? "Ready for another game?" : "Start when everyone is ready"}</h2><p className="waiting-start-hint">{canStart ? `${eligiblePlayers.length} active players are ready to play.` : `Need ${needsPlayers} more active player${needsPlayers === 1 ? "" : "s"}. Spectators, AFK, and disconnected players do not count.`}</p>{props.startError && <p className="waiting-start-error">{props.startError}</p>}</div><div className="waiting-host-actions"><button type="button" className="waiting-start-button" disabled={!canStart || props.startBusy} onClick={props.onStart}>{props.startBusy ? "Starting…" : rematch ? "Play again" : "Start game"}</button></div></> : <div><p className="waiting-card-kicker">Waiting for host</p><h2>{host ? `${host.nickname} will start ${rematch ? "the rematch" : "the game"}` : "Waiting for a host"}</h2><p className="waiting-start-hint">You can invite friends or mark yourself AFK while you wait.</p></div>}
    </section>

    {isHost && <details className="waiting-settings-inline" onToggle={(event) => setSettingsOpen(event.currentTarget.open)}><summary>Edit room settings</summary>{settingsOpen && <RoomSettingsEditor />}</details>}

    {finalScores && <section className="waiting-card waiting-results-card" aria-labelledby="waiting-results-title"><p className="waiting-card-kicker">Previous game</p><h2 id="waiting-results-title">{props.scoringMode === "default" ? `${finalScores[0]?.nickname ?? "The room"} wins!` : "Game complete"}</h2>{props.scoringMode === "default" ? <><p className="waiting-placement">Your place: #{Math.max(1, finalScores.findIndex((score) => score.token === myToken) + 1)}</p><ol>{finalScores.map((score, index) => <li key={score.token}><span>{["🥇", "🥈", "🥉"][index] ?? `#${index + 1}`} {score.nickname}{score.token === myToken ? " (you)" : ""}</span><strong>{score.score}</strong></li>)}</ol></> : <p>That game ended without scorekeeping. Thanks for playing!</p>}<div className="waiting-results-actions"><button type="button" onClick={props.onLeave}>Back to lobby</button>{props.hasDrawing && <button type="button" onClick={props.onSaveDrawing}>Save last drawing</button>}</div></section>}
    </div>
    <aside className="waiting-room-chat-column"><WaitingRoomChat messages={props.messages} /></aside>
    </div>
  </main>;
}
