import { useState } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import { recordRender } from "../lib/renderDiagnostics";
import type { AckResponse, ModerationState, PlayerInfo, ScoreEntry } from "../types";
import { PlayerList } from "./PlayerList";

interface RoomPlayersPanelProps {
  mode: "waiting" | "playing" | "game-end";
  players: PlayerInfo[];
  drawerId: string | null;
  myPlayerId: string | null;
  maxPlayers: number;
  showScores: boolean;
  finalScores: ScoreEntry[] | null;
  moderation: ModerationState;
}

export function RoomPlayersPanel({
  mode,
  players,
  drawerId,
  myPlayerId,
  maxPlayers,
  showScores,
  finalScores,
  moderation,
}: RoomPlayersPanelProps) {
  recordRender("players");
  const [promotionBusy, setPromotionBusy] = useState(false);
  const [promotionError, setPromotionError] = useState<string | null>(null);
  const activePlayers = players.filter((player) => !player.isSpectator);
  const spectators = players.filter((player) => player.isSpectator);
  const me = players.find((player) => player.playerId === myPlayerId);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const canPromoteSelf = mode === "waiting" && me?.isSpectator;
  const playerSpaceAvailable = activePlayers.length < maxPlayers;
  const showFinalStandings = mode !== "playing" && Boolean(finalScores) && showScores;
  const displayPlayers =
    showFinalStandings && finalScores
      ? activePlayers
          .map((player) => ({
            ...player,
            score:
              finalScores.find((score) => score.playerId === player.playerId)?.score ?? player.score,
          }))
          .sort((a, b) => b.score - a.score)
      : activePlayers;

  async function becomePlayer() {
    if (!canPromoteSelf || promotionBusy || !playerSpaceAvailable) return;
    setPromotionBusy(true);
    setPromotionError(null);
    try {
      const response = await emitWithAck<AckResponse>("become_player", {});
      if (!response.ok) setPromotionError(response.error || "Could not join as a player");
    } catch (promotionRequestError) {
      setPromotionError(
        socketRequestErrorMessage(promotionRequestError, "join as a player"),
      );
    } finally {
      setPromotionBusy(false);
    }
  }

  return (
    <section className="room-players-panel" aria-labelledby="room-players-title">
      <div className="room-panel-heading">
        <div>
          <p className="room-panel-kicker">
            {showFinalStandings ? "Final standings" : "People in room"}
          </p>
          <h2 id="room-players-title">
            Players ({activePlayers.length}/{maxPlayers})
          </h2>
        </div>
        <div className="room-panel-actions">
          {mode === "waiting" && (
            <span className={`waiting-ready-count ${eligiblePlayers.length >= 2 ? "is-ready" : ""}`}>
              {eligiblePlayers.length} ready
            </span>
          )}
          {spectators.length > 0 && (
            <div
              className="room-spectator-indicator"
              data-testid="spectator-indicator"
              tabIndex={0}
              aria-label={`${spectators.length} spectator${spectators.length === 1 ? "" : "s"}`}
              aria-describedby="room-spectator-tooltip"
            >
              <span className="room-spectator-icon" aria-hidden="true">👀</span>
              <span className="room-spectator-count">{spectators.length}</span>
              <div
                id="room-spectator-tooltip"
                className="room-spectator-tooltip"
                role="tooltip"
                data-testid="spectator-tooltip"
              >
                <strong>Spectators ({spectators.length})</strong>
                <ul>
                  {spectators.map((spectator) => (
                    <li key={spectator.playerId}>
                      <span
                        className="colored-player-name"
                        style={{ color: spectator.nameColor }}
                      >
                        {spectator.nickname}
                      </span>
                      {spectator.playerId === myPlayerId ? " (you)" : ""}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </div>
      <div data-testid="room-active-players">
        <PlayerList
          players={displayPlayers}
          drawerId={mode === "playing" ? drawerId : null}
          myPlayerId={myPlayerId}
          showScores={showScores && (mode !== "waiting" || showFinalStandings)}
          variant={showFinalStandings ? "game-end" : mode === "game-end" ? "waiting" : mode}
          allowVoting={mode === "playing"}
          moderation={moderation}
        />
      </div>
      {canPromoteSelf && (
        <div className="spectator-promotion" data-testid="spectator-promotion">
          <p>
            {playerSpaceAvailable
              ? "A player slot is available."
              : "Player slots are currently full."}
          </p>
          <button
            type="button"
            disabled={!playerSpaceAvailable || promotionBusy}
            onClick={() => void becomePlayer()}
          >
            {promotionBusy ? "Joining…" : "Join as player"}
          </button>
          {promotionError && (
            <p className="spectator-promotion-error" role="alert">
              {promotionError}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
