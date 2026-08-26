import { useState } from "react";
import { RoomSettingsEditor } from "./RoomSettingsEditor";
import { CustomPromptsPreview } from "./CustomPromptsPreview";
import { ModalShell } from "./ui/ModalShell";
import { Button } from "./ui/Button";
import { CopyIcon, GearIcon, LinkIcon } from "./icons";
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
  isPublic: boolean;
  maxPlayers: number;
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
  if (hidden) return "Hidden prompt";
  return ({
    checkpoints: "Timed hints",
    purchase: "Buy letters",
    wheel: "Wheel of Fortune",
    none: "No hints",
  })[mode];
}

function SettingChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="waiting-setting-chip">
      {label} <strong>{value}</strong>
    </span>
  );
}

export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  const { players, myPlayerId, isHost, finalScores, code } = props;
  const { notify } = useToast();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const activePlayers = players.filter((player) => !player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const me = players.find((player) => player.playerId === myPlayerId);
  const canStart = eligiblePlayers.length >= 2;
  const needsPlayers = Math.max(0, 2 - eligiblePlayers.length);
  const rematch = Boolean(finalScores);

  async function copyToClipboard(value: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      notify(`${what} copied.`, "success", 2500);
    } catch {
      notify(`Couldn’t copy the ${what.toLowerCase()}. Copy it from the address bar.`, "error");
    }
  }

  const promptsValue = props.customPromptsOnly
    ? `Custom prompts only (${props.customPromptCount})`
    : props.customPromptCount > 0
      ? `${props.customPromptCount} custom prompts + curated lists`
      : props.promptListSlugs && props.promptListSlugs.length > 1
        ? `${props.promptListSlugs.length} curated prompt lists`
        : "Curated prompt list";

  return (
    <main className="waiting-room" data-testid="waiting-room">
      <section className="waiting-card waiting-invite-card">
        <p className="section-label">
          {props.isPublic ? "Public room" : "Private room"} · {rematch ? "between games" : "waiting for players"}
        </p>
        <h1>{props.name}</h1>
        <p className="waiting-room-subtitle">
          {rematch
            ? "Game over. Send the code around for the next one."
            : "Send friends the code or the link — they can join mid-lobby."}
        </p>
        {code && (
          <div className="waiting-code-cells" role="img" aria-label={`Room code ${code}`}>
            {code.split("").map((character, index) => (
              <span key={index} aria-hidden="true">{character}</span>
            ))}
          </div>
        )}
        <div className="waiting-invite-actions">
          <Button
            variant="primary"
            iconLeft={<LinkIcon size={15} />}
            onClick={() => void copyToClipboard(window.location.href, "Invite link")}
          >
            Copy invite link
          </Button>
          <Button
            variant="ghost"
            iconLeft={<CopyIcon size={14} />}
            onClick={() => code && void copyToClipboard(code, "Room code")}
          >
            Copy code
          </Button>
        </div>
      </section>

      <section className="waiting-card waiting-settings-card" aria-labelledby="waiting-settings-title">
        <div className="waiting-settings-head">
          <h2 id="waiting-settings-title">Room settings</h2>
          {isHost && (
            <Button
              variant="secondary"
              compact
              iconLeft={<GearIcon size={15} />}
              onClick={() => setSettingsOpen(true)}
            >
              Edit settings
            </Button>
          )}
        </div>
        <div className="waiting-settings-chips">
          <SettingChip label="Players" value={`${props.maxPlayers} max`} />
          <SettingChip label="Rounds" value={String(props.rounds)} />
          <SettingChip label="Drawing time" value={`${props.drawingSeconds}s`} />
          <SettingChip
            label="Scoring"
            value={props.scoringMode === "none" ? "No scoring" : props.scoringMode === "pressure" ? "Pressure" : "Default"}
          />
          <SettingChip label="Hints" value={hintLabel(props.hintMode, props.hideMaskedPrompt)} />
          <SettingChip label="Prompts" value={promptsValue} />
          <SettingChip
            label="Drawing"
            value={describeDrawingRules(props.allowedTools, props.colorMode) ?? "Every tool and color"}
          />
          <SettingChip
            label="Spectators"
            value={props.spectatorsSeePrompt ? "See the prompt" : "Guess along"}
          />
        </div>
        {isHost && (
          <p className="waiting-settings-note">
            Only you can edit settings while the room waits. Everyone sees changes instantly.
          </p>
        )}
        {/* Players get a read-only look at the prompts; the host has the
            editor itself, and spectators are kept away from spoilers. */}
        {props.customPromptCount > 0 && !me?.isSpectator && !isHost && (
          <CustomPromptsPreview count={props.customPromptCount} />
        )}
      </section>

      {finalScores && (props.highlightCount > 0 || props.drawingCount > 0) && (
        <div className="waiting-room-actions">
          {props.highlightCount > 0 && (
            <Button variant="secondary" onClick={props.onViewHighlights}>
              View highlights
            </Button>
          )}
          {props.drawingCount > 0 && (
            <Button variant="secondary" onClick={props.onViewDrawings}>
              View drawings
            </Button>
          )}
        </div>
      )}

      <section className="waiting-card waiting-start-card" aria-live="polite">
        {isHost ? (
          <>
            <div>
              <h2>{rematch ? "Ready for a rematch?" : "Ready when you are"}</h2>
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
                className="btn btn-success btn-big waiting-start-button"
                disabled={!canStart || props.startBusy}
                onClick={props.onStart}
              >
                {props.startBusy ? "Starting…" : rematch ? "Rematch" : "Start game"}
              </button>
            </div>
          </>
        ) : (
          <div>
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

      {settingsOpen && (
        <ModalShell
          labelledBy="room-settings-title"
          cardClassName="room-settings-modal-card"
          onDismiss={() => setSettingsOpen(false)}
        >
          <RoomSettingsEditor />
        </ModalShell>
      )}
    </main>
  );
}
