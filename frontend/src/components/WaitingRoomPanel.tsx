import { RoomSettingsEditor } from "./RoomSettingsDialog";
import { CustomWordsPreview } from "./CustomWordsPreview";
import type { HintMode, PlayerInfo, ScoreEntry, ScoringMode } from "../types";

interface WaitingRoomPanelProps {
  name: string;
  isPublic: boolean;
  rounds: number;
  drawingSeconds: number;
  customWordCount: number;
  customWordsOnly: boolean;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeeSolution: boolean;
  hideMaskedPrompt: boolean;
  players: PlayerInfo[];
  myToken: string | null;
  isHost: boolean;
  finalScores: ScoreEntry[] | null;
  startBusy: boolean;
  startError: string | null;
  onStart: () => void;
  onLeave: () => void;
  onSaveDrawing: () => void;
  hasDrawing: boolean;
}

function hintLabel(mode: HintMode, hidden: boolean) {
  if (hidden) return "Prompt details hidden";
  return ({
    checkpoints: "Timed letter hints",
    purchase: "Buyable letter hints",
    wheel: "Wheel-style letter hints",
    none: "No letter hints",
  })[mode];
}

export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  const { players, myToken, isHost, finalScores } = props;
  const activePlayers = players.filter((player) => !player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const me = players.find((player) => player.token === myToken);
  const canStart = eligiblePlayers.length >= 2;
  const needsPlayers = Math.max(0, 2 - eligiblePlayers.length);
  const rematch = Boolean(finalScores);

  return (
    <main className="waiting-room" data-testid="waiting-room">
      <section className="waiting-room-intro">
        <div>
          <p className="waiting-room-eyebrow">
            {props.isPublic ? "Public room" : "Private room"}
          </p>
          <h1>{props.name}</h1>
          <p className="waiting-room-subtitle">
            {rematch
              ? "Last game complete. The lobby is ready for a rematch."
              : "Get everyone ready before the first round."}
          </p>
        </div>
      </section>

      {isHost ? (
        <RoomSettingsEditor />
      ) : (
        <section className="waiting-card waiting-rules-card" aria-labelledby="waiting-rules-title">
          <p className="waiting-card-kicker">Room rules</p>
          <h2 id="waiting-rules-title">How this game will play</h2>
          <ul className="waiting-rules-list">
            <li>
              {props.rounds} round{props.rounds === 1 ? "" : "s"} each ·{" "}
              {props.drawingSeconds}s to draw
            </li>
            <li>
              {props.scoringMode === "default"
                ? "Points for fast, correct guesses"
                : "No scorekeeping"}
            </li>
            <li>{hintLabel(props.hintMode, props.hideMaskedPrompt)}</li>
            <li>
              {props.customWordsOnly
                ? `Custom words only (${props.customWordCount})`
                : props.customWordCount
                  ? `${props.customWordCount} custom words included`
                  : "Built-in word list"}
            </li>
            <li>
              {props.spectatorsSeeSolution
                ? "Spectators can see the solution"
                : "Spectators guess along"}
            </li>
          </ul>
          {props.customWordCount > 0 && !me?.isSpectator && (
            <CustomWordsPreview count={props.customWordCount} />
          )}
        </section>
      )}

      <section className="waiting-card waiting-start-card" aria-live="polite">
        {isHost ? (
          <>
            <div>
              <p className="waiting-card-kicker">Host controls</p>
              <h2>{rematch ? "Ready for another game?" : "Start when everyone is ready"}</h2>
              <p className="waiting-start-hint">
                {canStart
                  ? `${eligiblePlayers.length} active players are ready to play.`
                  : `Need ${needsPlayers} more active player${needsPlayers === 1 ? "" : "s"}. Spectators, AFK, and disconnected players do not count.`}
              </p>
              {props.startError && <p className="waiting-start-error">{props.startError}</p>}
            </div>
            <div className="waiting-host-actions">
              <button
                type="button"
                className="waiting-start-button"
                disabled={!canStart || props.startBusy}
                onClick={props.onStart}
              >
                {props.startBusy ? "Starting…" : rematch ? "Play again" : "Start game"}
              </button>
            </div>
          </>
        ) : (
          <div>
            <p className="waiting-card-kicker">Waiting for host</p>
            <h2>
              {host
                ? <><span className="colored-player-name" style={{ color: host.nameColor }}>{host.nickname}</span> will start {rematch ? "the rematch" : "the game"}</>
                : "Waiting for a host"}
            </h2>
            <p className="waiting-start-hint">
              You can invite friends or mark yourself AFK while you wait.
            </p>
          </div>
        )}
      </section>

      {finalScores && (
        <section
          className="waiting-card waiting-results-card"
          aria-labelledby="waiting-results-title"
        >
          <p className="waiting-card-kicker">Previous game</p>
          <h2 id="waiting-results-title">
            {props.scoringMode === "default"
              ? <><span className="colored-player-name" style={{ color: finalScores[0]?.nameColor }}>{finalScores[0]?.nickname ?? "The room"}</span> wins!</>
              : "Game complete"}
          </h2>
          {props.scoringMode === "default" ? (
            <>
              <p className="waiting-placement">
                Your place: #
                {Math.max(1, finalScores.findIndex((score) => score.token === myToken) + 1)}
              </p>
              <ol>
                {finalScores.map((score, index) => (
                  <li key={score.token}>
                    <span>
                      {["🥇", "🥈", "🥉"][index] ?? `#${index + 1}`}{" "}
                      <span className="colored-player-name" style={{ color: score.nameColor }}>
                        {score.nickname}
                      </span>
                      {score.token === myToken ? " (you)" : ""}
                    </span>
                    <strong>{score.score}</strong>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p>That game ended without scorekeeping. Thanks for playing!</p>
          )}
          <div className="waiting-results-actions">
            <button type="button" onClick={props.onLeave}>
              Back to lobby
            </button>
            {props.hasDrawing && (
              <button type="button" onClick={props.onSaveDrawing}>
                Save last drawing
              </button>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
