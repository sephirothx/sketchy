import { useState } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse, PlayerInfo, ScoreEntry } from "../types";
import { PlayerList } from "./PlayerList";

interface RoomPlayersPanelProps {
  mode: "waiting" | "playing" | "game-end";
  players: PlayerInfo[];
  drawerToken: string | null;
  myToken: string | null;
  maxPlayers: number;
  showScores: boolean;
  finalScores: ScoreEntry[] | null;
}

export function RoomPlayersPanel({
  mode,
  players,
  drawerToken,
  myToken,
  maxPlayers,
  showScores,
  finalScores,
}: RoomPlayersPanelProps) {
  const [promotionBusy, setPromotionBusy] = useState(false);
  const [promotionError, setPromotionError] = useState<string | null>(null);
  const activePlayers = players.filter((player) => !player.isSpectator);
  const spectators = players.filter((player) => player.isSpectator);
  const me = players.find((player) => player.token === myToken);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const canPromoteSelf = mode === "waiting" && me?.isSpectator;
  const playerSpaceAvailable = activePlayers.length < maxPlayers;
  const displayPlayers =
    mode === "game-end" && finalScores
      ? activePlayers
          .map((player) => ({
            ...player,
            score:
              finalScores.find((score) => score.token === player.token)?.score ?? player.score,
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
            {mode === "game-end" ? "Final standings" : "People in room"}
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
                    <li key={spectator.token}>
                      {spectator.nickname}{spectator.token === myToken ? " (you)" : ""}
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
          drawerToken={mode === "playing" ? drawerToken : null}
          myToken={myToken}
          showScores={mode !== "waiting" && showScores}
          variant={mode === "game-end" && !showScores ? "waiting" : mode}
          allowVoting={mode === "playing"}
          votingPopulation={players}
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
