import { useEffect, useRef, useState } from "react";
import { RoomSettingsEditor } from "./RoomSettingsEditor";
import { CustomPromptsPreview } from "./CustomPromptsPreview";
import { copyText } from "../lib/clipboard";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { describeDrawingRules } from "../lib/drawingRules";
import { useToast } from "../lib/toast";
import type {
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PlayerInfo,
  ScoreEntry,
  ScoringMode,
} from "../types";

interface WaitingRoomPanelProps {
  name: string;
  code: string | null;
  maxPlayers: number;
  isPublic: boolean;
  rounds: number;
  drawingSeconds: number;
  customPromptCount: number;
  customPromptsOnly: boolean;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptListSlugs?: string[];
  players: PlayerInfo[];
  myPlayerId: string | null;
  isHost: boolean;
  finalScores: ScoreEntry[] | null;
  startBusy: boolean;
  startError: string | null;
  onStart: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
  highlightCount: number;
  onViewHighlights: () => void;
}

function hintLabel(mode: HintMode, hidden: boolean) {
  if (hidden) return "Blanks hidden from guessers";
  return ({
    checkpoints: "Timed hints",
    purchase: "Buy letters against your turn score",
    wheel: "Wheel of Fortune",
    none: "No hints",
  })[mode];
}

function InviteCard({
  code,
  playersHere,
  maxPlayers,
}: {
  code: string;
  playersHere: number;
  maxPlayers: number;
}) {
  const { notify } = useToast();
  const [copied, setCopied] = useState<"link" | "code" | null>(null);
  const copyResetRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (copyResetRef.current != null) window.clearTimeout(copyResetRef.current);
  }, []);

  async function copy(kind: "link" | "code") {
    const text = kind === "link" ? `${window.location.origin}/room/${code}` : code;
    if (await copyText(text)) {
      notify(kind === "link" ? "Invite link copied." : "Room code copied.", "success", 2500);
      setCopied(kind);
      if (copyResetRef.current != null) window.clearTimeout(copyResetRef.current);
      copyResetRef.current = window.setTimeout(() => setCopied(null), 1800);
    } else {
      notify("Couldn’t copy. Share the code from the top of the page instead.", "error");
    }
  }

  return (
    <section className="waiting-card waiting-invite-card" aria-labelledby="waiting-invite-title">
      <div>
        <p className="waiting-card-kicker">
          {playersHere} of {maxPlayers} players here
        </p>
        <h2 id="waiting-invite-title">Invite friends</h2>
        <p className="waiting-invite-hint">
          Share the invite link or the room code — anyone with it can join.
        </p>
      </div>
      <div className="waiting-invite-actions">
        <span className="waiting-invite-code" aria-label={`Room code ${code}`}>
          {code}
        </span>
        <div className="waiting-invite-buttons">
          <button
            type="button"
            className="waiting-invite-link-button"
            onClick={() => void copy("link")}
          >
            {copied === "link" ? "Copied!" : "Copy invite link"}
          </button>
          <button
            type="button"
            className="waiting-invite-code-button"
            onClick={() => void copy("code")}
          >
            {copied === "code" ? "Copied!" : "Copy code"}
          </button>
        </div>
      </div>
    </section>
  );
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
              ? "Game over. Ready for a rematch."
              : "Get everyone ready before the first round."}
          </p>
        </div>
        {finalScores && (
          <div className="waiting-room-actions">
            {props.highlightCount > 0 && (
              <button type="button" onClick={props.onViewHighlights}>
                View highlights
              </button>
            )}
            {props.drawingCount > 0 && (
              <button type="button" onClick={props.onViewDrawings}>
                View drawings
              </button>
            )}
          </div>
        )}
      </section>

      {props.code && (
        <InviteCard
          code={props.code}
          playersHere={activePlayers.length}
          maxPlayers={props.maxPlayers}
        />
      )}

      {isHost ? (
        <RoomSettingsEditor />
      ) : (
        <section className="waiting-card waiting-rules-card" aria-labelledby="waiting-rules-title">
          <p className="waiting-card-kicker">Room settings</p>
          <h2 id="waiting-rules-title">How this game will play</h2>
          <ul className="waiting-rules-list">
            <li>
              {props.rounds} round{props.rounds === 1 ? "" : "s"} each ·{" "}
              {props.drawingSeconds}s to draw
            </li>
            <li>
              {props.scoringMode === "none"
                ? "No scoring"
                : props.scoringMode === "pressure"
                  ? "Points drain faster once someone guesses"
                  : "Points for fast, correct guesses"}
            </li>
            <li>{hintLabel(props.hintMode, props.hideMaskedPrompt)}</li>
            <li>
              {props.customPromptsOnly
                ? `Custom prompts only (${props.customPromptCount})`
                : props.customPromptCount
                  ? `${props.customPromptCount} custom prompts + curated lists`
                  : props.promptListSlugs && props.promptListSlugs.length > 1
                    ? `${props.promptListSlugs.length} curated prompt lists`
                    : "Curated prompt list"}
            </li>
            <li>
              {props.spectatorsSeePrompt
                ? "Spectators can see the prompt"
                : "Spectators guess along"}
            </li>
            <li>{describeDrawingRules(props.allowedTools, props.colorMode) ?? "Every tool and color"}</li>
          </ul>
          {props.customPromptCount > 0 && !me?.isSpectator && (
            <CustomPromptsPreview count={props.customPromptCount} />
          )}
        </section>
      )}

      <section className="waiting-card waiting-start-card" aria-live="polite">
        {isHost ? (
          <>
            <div>
              <p className="waiting-card-kicker">Host controls</p>
              <h2>{rematch ? "Ready for a rematch?" : "Start when everyone is ready"}</h2>
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
                {props.startBusy ? "Starting…" : rematch ? "Rematch" : "Start game"}
              </button>
            </div>
          </>
        ) : (
          <div>
            <p className="waiting-card-kicker">Waiting for host</p>
            <h2>
              {host
                ? <><span className={playerNameClass(host.isAnonymous)} style={playerNameStyle(host.nameColor, host.isAnonymous)}>{host.nickname}</span> will start {rematch ? "the rematch" : "the game"}</>
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
