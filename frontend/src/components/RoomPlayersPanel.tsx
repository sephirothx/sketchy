import { recordRender } from "../lib/renderDiagnostics";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import type { ModerationState, PlayerInfo, ScoreEntry } from "../types";
import { PlayerList } from "./PlayerList";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { PHONE_ROOM_QUERY } from "../lib/roomLayout";
import { SpectatorPromotion } from "./SpectatorPromotion";
import { EyeIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

interface RoomPlayersPanelProps {
  mode: "waiting" | "playing" | "game-end";
  players: PlayerInfo[];
  drawerId: string | null;
  myPlayerId: string | null;
  maxPlayers: number;
  showScores: boolean;
  finalScores: ScoreEntry[] | null;
  moderation: ModerationState;
  turnCorrectGuesses?: Record<string, number>;
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
  turnCorrectGuesses,
}: RoomPlayersPanelProps) {
  recordRender("players");
  const activePlayers = players.filter((player) => !player.isSpectator);
  const spectators = players.filter((player) => player.isSpectator);
  const me = players.find((player) => player.playerId === myPlayerId);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  // A phone's waiting room hides this panel and offers the seat in its roster
  // grid instead (#1269); rendering it here too left a second, hidden offer.
  const isPhone = useMediaQuery(PHONE_ROOM_QUERY);
  const canPromoteSelf = mode === "waiting" && me?.isSpectator && !isPhone;
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

  return (
    <section className="room-players-panel" aria-labelledby="room-players-title">
      <div className="room-panel-heading">
        <div>
          {showFinalStandings && <p className="section-label room-panel-kicker">{ui.roomPlayersPanel.finalStandings}</p>}
          <div className="room-players-title-row">
            <h2 id="room-players-title" className="panel-title" tabIndex={-1}>{ui.roomPlayersPanel.players}</h2>
            <span
              className="room-player-occupancy"
              aria-label={ui.roomPlayersPanel.playersOfCapacity({ here: activePlayers.length, capacity: maxPlayers })}
            >
              {activePlayers.length}/{maxPlayers}
            </span>
          </div>
        </div>
        <div className="room-panel-actions">
          {/* Only when it says something the count beside the heading does
              not: somebody seated who is away or disconnected, and so does
              not count towards a start. "2/8" and "2 ready" said one fact
              twice the rest of the time. */}
          {mode === "waiting" && eligiblePlayers.length !== activePlayers.length && (
            <span className={`waiting-ready-count ${eligiblePlayers.length >= 2 ? "is-ready" : ""}`}>
              {ui.roomPlayersPanel.readyCount({ count: eligiblePlayers.length })}
            </span>
          )}
          {spectators.length > 0 && (
            <div
              className="room-spectator-indicator"
              data-testid="spectator-indicator"
              tabIndex={0}
              aria-label={ui.roomPlayersPanel.spectatorCount({ count: spectators.length })}
              aria-describedby="room-spectator-tooltip"
            >
              <span className="room-spectator-icon" aria-hidden="true"><EyeIcon size={14} /></span>
              <span className="room-spectator-count">{spectators.length}</span>
              <div
                id="room-spectator-tooltip"
                className="room-spectator-tooltip"
                role="tooltip"
                data-testid="spectator-tooltip"
              >
                <strong>{ui.roomPlayersPanel.spectatorsHeading({ count: spectators.length })}</strong>
                <ul>
                  {spectators.map((spectator) => (
                    <li key={spectator.playerId}>
                      <span
                        className={playerNameClass(spectator.isAnonymous)}
                        style={playerNameStyle(spectator.nameColor, spectator.isAnonymous)}
                      >
                        {spectator.nickname}
                      </span>
                      {spectator.playerId === myPlayerId ? ` ${ui.roomPlayersPanel.you}` : ""}
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
          turnCorrectGuesses={mode === "playing" ? turnCorrectGuesses : undefined}
        />
      </div>
      {canPromoteSelf && <SpectatorPromotion playerSpaceAvailable={playerSpaceAvailable} />}
    </section>
  );
}
