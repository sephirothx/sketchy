import { useState, type ReactNode } from "react";
import { QRCodeSVG } from "qrcode.react";
import { RoomSettingsEditor } from "./RoomSettingsEditor";
import { CustomPromptsPreview } from "./CustomPromptsPreview";
import { ModalShell } from "./ui/ModalShell";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { BrushIcon, BulbIcon, ClockIcon, CopyIcon, LinkIcon, ListIcon, PlusIcon, RoundsIcon, SlidersIcon, TrophyIcon, UsersIcon } from "./icons";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { roomFacts, roomFactsSummary, type RoomFactKey } from "../lib/roomFacts";
import { InviteFriendsList } from "./InviteFriendsList";
import { useLobbyChannel } from "../hooks/useLobbyChannel";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useToast } from "../lib/toast";
import type {
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PlayerInfo,
  ScoreEntry,
  ScoringMode,
} from "../types";

/** One icon per fact, in the order `roomFacts` returns them. */
const ROOM_FACT_ICONS: Record<RoomFactKey, ReactNode> = {
  players: <UsersIcon size={12} />,
  rounds: <RoundsIcon size={12} />,
  drawingTime: <ClockIcon size={12} />,
  scoring: <TrophyIcon size={12} />,
  hints: <BulbIcon size={12} />,
  drawingRules: <BrushIcon size={12} />,
};

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
  /** The way out for whoever landed in the wrong room. */
  onLeave: () => void;
  drawingCount: number;
  onViewDrawings: () => void;
  highlightCount: number;
  onViewHighlights: () => void;
}


export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  // The waiting room is the one place inside a room that needs to know
  // who is around: it is where you are trying to get people in, and it is
  // not mid-game. Dropped again the moment the game starts.
  useLobbyChannel();
  const { players, myPlayerId, isHost, finalScores, code } = props;
  const { notify } = useToast();
  // Narrow only. Above this the players panel has a column of its own and
  // says more than a grid of faces can, so rendering both would put every
  // nickname on the page twice.
  const isNarrow = useMediaQuery("(max-width: 900px)");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const activePlayers = players.filter((player) => !player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const me = players.find((player) => player.playerId === myPlayerId);
  const canStart = eligiblePlayers.length >= 2;
  const needsPlayers = Math.max(0, 2 - eligiblePlayers.length);
  // The button says how many are missing; the tooltip says what counts, which
  // is the part nobody needs until they wonder why a spectator is not enough.
  const startBlockedReason =
    "Spectators, AFK, and disconnected players do not count towards the two active players a game needs.";
  const rematch = Boolean(finalScores);
  // The address bar itself, which is what the room chip and the Room menu
  // copy too — so the code on the card, the link that is shared, and the QR
  // beside it are provably one destination.
  const inviteUrl = window.location.href;

  async function copyToClipboard(value: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      notify(`${what} copied.`, "success", 2500);
    } catch {
      notify(`Couldn’t copy the ${what.toLowerCase()}. Copy it from the address bar.`, "error");
    }
  }

  // The first three are what everyone wants to know; the rest appear only
  // when the host has moved them off their defaults, which is when they are
  // worth a line. Eight chips said all of it always, and spent 250px doing it.
  // The OS share sheet is how a code actually reaches a group chat. Where
  // there is none — every desktop browser but Safari — copying the link is
  // the same job done by hand. Both it and the QR code carry `inviteUrl`, so
  // scanning the card and sending it cannot land people in different rooms.
  async function shareInvite() {
    const url = inviteUrl;
    if (navigator.share) {
      try {
        await navigator.share({ title: props.name, text: `Join my Sketchy room: ${code ?? ""}`, url });
        return;
      } catch (error) {
        // A cancelled share is not a failure, and must not fall through to a
        // copy the player did not ask for.
        if ((error as DOMException)?.name === "AbortError") return;
      }
    }
    await copyToClipboard(url, "Invite link");
  }

  const promptsValue = props.customPromptsOnly
    ? `Custom prompts only (${props.customPromptCount})`
    : props.customPromptCount > 0
      ? `${props.customPromptCount} custom prompts + curated lists`
      : props.promptListSlugs && props.promptListSlugs.length > 1
        ? `${props.promptListSlugs.length} curated prompt lists`
        : null;
  // The six facts, from the one place that decides what they are and in
  // which order (R-UX-09) — the lobby card and the invite page read the same
  // list. The player count is the live one, not the room summary's.
  const factsInput = {
    playerCount: activePlayers.length,
    maxPlayers: props.maxPlayers,
    rounds: props.rounds,
    drawingSeconds: props.drawingSeconds,
    scoringMode: props.scoringMode,
    hintMode: props.hintMode,
    hideMaskedPrompt: props.hideMaskedPrompt,
    allowedTools: props.allowedTools,
    colorMode: props.colorMode,
  };
  const facts = roomFacts(factsInput);
  const listCount = props.promptListSlugs?.length ?? 0;
  const promptsLine = [
    promptsValue ?? `${listCount} curated prompt ${listCount === 1 ? "list" : "lists"}`,
    props.spectatorsSeePrompt ? "spectators see the prompt" : null,
  ].filter(Boolean).join(" · ");


  return (
    <main className="waiting-room" data-testid="waiting-room">
      {/* Which room this is, out of the invite card. It is the one thing on
          the screen that is not about getting people into it. */}
      <header className="waiting-room-head">
        <h1>{props.name}</h1>
        <p className="section-label">
          {props.isPublic ? "Public room" : "Private room"} · {rematch ? "between games" : "waiting for players"}
        </p>
      </header>

      {/* The code, read at a glance or tapped to copy, and one way to send it.
          Six bordered cells and two buttons spent 237px on that. */}
      <section className="waiting-card waiting-invite-card">
        <p className="waiting-invite-kicker">Invite your friends</p>
        <div className="waiting-invite-main">
          {/* Beside the code because it answers the same question for the
              person sitting across the table: the code they would type, and
              the link they can point a camera at instead. Drawn on its own
              white plate, whose padding is the quiet zone the format needs -
              a dark-theme card would otherwise leave nothing to scan. */}
          {code && (
            <div className="waiting-invite-qr">
              <QRCodeSVG
                value={inviteUrl}
                size={104}
                marginSize={0}
                level="M"
                bgColor="#ffffff"
                fgColor="#12100e"
                // The <title> alone is skipped by readers that treat an SVG
                // as a graphic with no role; role="img" is what makes it the
                // element's name.
                role="img"
                title={`Scan to join room ${code}`}
              />
            </div>
          )}
          {code && (
            <p className="waiting-code" aria-label={`Room code ${code}`}>{code}</p>
          )}
        </div>
        {/* Under both, across the card: two buttons squeezed into what is
            left beside a QR code is how a phone gets a truncated one. */}
        <div className="waiting-invite-actions">
          <Button variant="primary" iconLeft={<LinkIcon size={15} />} onClick={() => void shareInvite()}>
            Share the link
          </Button>
          {/* A button of its own, not a link pretending to be one: it is the
              other half of the same job as Share, on a card whose whole
              purpose is these two. */}
          <Button
            variant="secondary"
            iconLeft={<CopyIcon size={15} />}
            onClick={() => code && void copyToClipboard(code, "Room code")}
          >
            Copy code
          </Button>
        </div>
        {/* The same job as Share, for the people you already play with: no
            clipboard, no other app, and no code leaving this room. */}
        <InviteFriendsList />
      </section>

      {/* Who is here, as faces rather than a list in another column. The one
          thing you watch while waiting used to be the last thing on the page,
          below the chat card. */}
      {isNarrow && <section className="waiting-card waiting-roster" aria-labelledby="waiting-roster-title">
        <div className="waiting-roster-head">
          <h2 id="waiting-roster-title">In the room</h2>
          <span className="waiting-roster-count">
            {activePlayers.length} of {props.maxPlayers}
          </span>
        </div>
        <ul className="waiting-roster-grid">
          {activePlayers.map((player) => (
            <li
              key={player.playerId}
              className="waiting-roster-tile"
            >
              <Avatar
                name={player.nickname}
                nameColor={player.nameColor}
                avatarUrl={player.avatarUrl}
                isAnonymous={player.isAnonymous}
                isHost={player.isHost}
                isSelf={player.playerId === myPlayerId}
                size={46}
              />
              <span className="waiting-roster-name">
                <span
                  className={playerNameClass(player.isAnonymous)}
                  style={playerNameStyle(player.nameColor, player.isAnonymous)}
                >
                  {player.nickname}
                </span>
                {player.playerId === myPlayerId && (
                  <span className="visually-hidden">(you)</span>
                )}
                {player.isHost && <span className="visually-hidden">Host</span>}
              </span>
            </li>
          ))}
          {activePlayers.length < props.maxPlayers && (
            <li className="waiting-roster-tile is-empty">
              <span className="waiting-roster-empty-avatar" aria-hidden="true">
                <PlusIcon size={18} />
              </span>
              <span className="waiting-roster-name">Invite</span>
            </li>
          )}
        </ul>
      </section>}

      {/* The room's settings, for everyone: the same six facts the lobby card
          and the invite page show, as tiles readable from across the table,
          with the one-line summary above them. The host has the way in; a
          guest sees whose settings they are. */}
      <section
        className="waiting-card waiting-rules waiting-settings-row"
        aria-labelledby="waiting-rules-title"
      >
        <div className="waiting-rules-head">
          <div className="waiting-rules-title">
            <h2 id="waiting-rules-title">Room rules</h2>
            <p className="waiting-settings-summary">{roomFactsSummary(factsInput)}</p>
          </div>
          {isHost ? (
            <Button
              variant="secondary"
              compact
              className="waiting-settings-edit-button"
              iconLeft={<SlidersIcon size={15} />}
              onClick={() => setSettingsOpen(true)}
            >
              Edit room rules
            </Button>
          ) : host ? (
            <span className="waiting-rules-host">
              <span className={playerNameClass(host.isAnonymous)} style={playerNameStyle(host.nameColor, host.isAnonymous)}>{host.nickname}</span> sets these
            </span>
          ) : null}
        </div>
        <dl className="waiting-rules-grid">
          {facts.map((fact) => (
            <div className="rule-tile" key={fact.key}>
              <dt>{ROOM_FACT_ICONS[fact.key]}{fact.label}</dt>
              <dd>{fact.value}{fact.detail && <small>{fact.detail}</small>}</dd>
            </div>
          ))}
        </dl>
        <p className="waiting-rules-prompts">
          <ListIcon size={13} />
          <span>{promptsLine}</span>
        </p>
      </section>

      {/* Players get a read-only look at the prompts; the host has the editor
          itself, and spectators are kept away from spoilers. */}
      {props.customPromptCount > 0 && !me?.isSpectator && !isHost && (
        <CustomPromptsPreview count={props.customPromptCount} />
      )}

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

      {/* The button and nothing else. What was around it — a heading saying
          the host was ready, and a paragraph explaining why they were not —
          is either obvious or belongs on the button itself. */}
      <section className="waiting-card waiting-start-card" aria-live="polite">
        {isHost ? (
          <>
            {props.startError && <p className="waiting-start-error">{props.startError}</p>}
            <button
              type="button"
              className="btn btn-warm btn-big waiting-start-button"
              disabled={!canStart || props.startBusy}
              onClick={props.onStart}
              title={canStart ? undefined : startBlockedReason}
            >
              {props.startBusy
                ? "Starting…"
                : canStart
                  ? rematch ? "Rematch" : "Start game"
                  : `Need ${needsPlayers} more player${needsPlayers === 1 ? "" : "s"}`}
            </button>
          </>
        ) : (
          <p className="waiting-start-waiting">
            {host
              ? <><span className={playerNameClass(host.isAnonymous)} style={playerNameStyle(host.nameColor, host.isAnonymous)}>{host.nickname}</span> will start {rematch ? "the rematch" : "the game"}</>
              : "Waiting for a host"}
          </p>
        )}
        {/* Wrong room, wrong night: the exit lives here as well as in the
            Room menu, quiet enough not to compete with Start. */}
        <button type="button" className="btn btn-ghost waiting-leave-link" onClick={props.onLeave}>
          Leave the room
        </button>
      </section>

      {settingsOpen && (
        <ModalShell
          labelledBy="room-settings-title"
          cardClassName="room-settings-modal-card"
          onDismiss={() => setSettingsOpen(false)}
        >
          <RoomSettingsEditor
            onSaved={() => setSettingsOpen(false)}
            onCancel={() => setSettingsOpen(false)}
          />
        </ModalShell>
      )}
    </main>
  );
}
