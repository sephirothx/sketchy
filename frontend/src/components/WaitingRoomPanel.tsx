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
  myPlayerId: string | null;
  isHost: boolean;
  finalScores: ScoreEntry[] | null;
  startBusy: boolean;
  startError: string | null;
  onStart: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
}

function hintLabel(mode: HintMode, hidden: boolean) {
  if (hidden) return "Blanks hidden from guessers";
  return ({
    checkpoints: "Timed letter hints",
    purchase: "Buy letters with points",
    wheel: "Wheel of Fortune letter buys",
    none: "No letter hints",
  })[mode];
}

export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  const { players, myPlayerId, isHost, finalScores } = props;
  const activePlayers = players.filter((player) => !player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const me = players.find((player) => player.playerId === myPlayerId);
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
        {finalScores && (
          <div className="waiting-room-actions">
            {props.drawingCount > 0 && (
              <button type="button" onClick={props.onViewDrawings}>
                View drawings
              </button>
            )}
          </div>
        )}
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
                ? "Spectators can see the prompt"
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

    </main>
  );
}
