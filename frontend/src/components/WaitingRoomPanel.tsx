import { Fragment, useState } from "react";
import { RoomSettingsEditor } from "./RoomSettingsEditor";
import { CustomPromptsPreview } from "./CustomPromptsPreview";
import { ModalShell } from "./ui/ModalShell";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { BrushIcon, BulbIcon, ClockIcon, CopyIcon, LinkIcon, ListIcon, PlusIcon, RoundsIcon, SlidersIcon, TrophyIcon, UsersIcon } from "./icons";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { describeDrawingRules } from "../lib/drawingRules";
import { HINT_OPTIONS, SCORING_OPTIONS, hintLabelFor, scoringLabelFor } from "../lib/roomSetup";
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
  // the same job done by hand.
  async function shareInvite() {
    const url = window.location.href;
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
  // The one-line summary above the tiles: what a game here is like, in the
  // words the lobby card uses. Prompts and drawing rules have their own
  // places on the card, so they are not repeated here.
  const settingsFacts = [
    `${props.rounds} ${props.rounds === 1 ? "round" : "rounds"}`,
    `${props.drawingSeconds}s`,
    hintLabelFor(props.hintMode, props.hideMaskedPrompt),
    props.scoringMode === "none" ? "No scoring" : null,
  ].filter((fact): fact is string => Boolean(fact));
  const seatsFree = Math.max(0, props.maxPlayers - activePlayers.length);
  // The same rough estimate the create page shows: every player draws once
  // per round, and a turn is the drawing time plus choosing and results.
  const estimateMinutes = Math.max(
    1,
    Math.round((Math.max(2, activePlayers.length) * props.rounds * (props.drawingSeconds + 24)) / 60),
  );
  const scoringDescription = SCORING_OPTIONS.find((option) => option.value === props.scoringMode)?.description ?? "";
  const hintDescription = props.hideMaskedPrompt
    ? "Blanks are hidden, so there is nothing to reveal."
    : HINT_OPTIONS.find((option) => option.value === props.hintMode)?.description ?? "";
  // Null when the room restricts nothing: the defaults are worth no words.
  const drawingRules = describeDrawingRules(props.allowedTools, props.colorMode);
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
        {code && (
          <p className="waiting-code" aria-label={`Room code ${code}`}>{code}</p>
        )}
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
            <p className="waiting-settings-summary">
              {settingsFacts.map((fact, index) => (
                <Fragment key={fact}>
                  {index > 0 && <span className="waiting-settings-sep" aria-hidden="true"> · </span>}
                  <span>{fact}</span>
                </Fragment>
              ))}
            </p>
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
          <div className="rule-tile">
            <dt><UsersIcon size={12} />Players</dt>
            <dd>{activePlayers.length} of {props.maxPlayers}<small>{seatsFree === 0 ? "the room is full" : `${seatsFree} ${seatsFree === 1 ? "seat" : "seats"} free`}</small></dd>
          </div>
          <div className="rule-tile">
            <dt><RoundsIcon size={12} />Rounds</dt>
            <dd>{props.rounds}<small>everyone draws {props.rounds === 1 ? "once" : `${props.rounds} times`}</small></dd>
          </div>
          <div className="rule-tile">
            <dt><ClockIcon size={12} />Drawing time</dt>
            <dd>{props.drawingSeconds}s<small>about {estimateMinutes} min with {Math.max(2, activePlayers.length)}</small></dd>
          </div>
          <div className="rule-tile">
            <dt><TrophyIcon size={12} />Scoring</dt>
            <dd>{scoringLabelFor(props.scoringMode)}<small>{scoringDescription}</small></dd>
          </div>
          <div className="rule-tile">
            <dt><BulbIcon size={12} />Hints</dt>
            <dd>{hintLabelFor(props.hintMode, props.hideMaskedPrompt)}<small>{hintDescription}</small></dd>
          </div>
          <div className="rule-tile">
            <dt><BrushIcon size={12} />Drawing rules</dt>
            <dd>{drawingRules ?? "All tools"}<small>{drawingRules ? "" : "all colors"}</small></dd>
          </div>
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
