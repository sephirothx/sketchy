import { useEffect, useRef, useState } from "react";
import { RoomSettingsEditor } from "./RoomSettingsEditor";
import { CustomPromptsPreview } from "./CustomPromptsPreview";
import { ModalShell } from "./ui/ModalShell";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { BackIcon, BrushIcon, CopyIcon, LinkIcon, PencilIcon, PlayIcon, PlusIcon } from "./icons";
import { RoomFacts } from "./RoomFacts";
import { ScratchPad } from "./ScratchPad";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import { InviteFriendsList } from "./InviteFriendsList";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useToast } from "../lib/toast";
import { useRoomFriendsStore } from "../store/roomFriendsStore";
import type {
  PromptLanguage,
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PlayerInfo,
  ScoreEntry,
  ScoringMode,
} from "../types";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import "../styles/lazy/toolbar.css";

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
  promptLanguage: PromptLanguage;
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


export function WaitingRoomPanel(props: WaitingRoomPanelProps) {
  const { players, myPlayerId, isHost, finalScores, code } = props;
  const { notify } = useToast();
  // The same seat set the sidebar roster marks from, so a friendship reads
  // identically whichever of the two is on screen (R-FRIEND-13).
  const friendSeats = useRoomFriendsStore((state) => state.seatIds);
  // Narrow only. Above this the players panel has a column of its own and
  // says more than a grid of faces can, so rendering both would put every
  // nickname on the page twice.
  const isNarrow = useMediaQuery("(max-width: 900px)");
  const [settingsOpen, setSettingsOpen] = useState(false);
  // The scratch pad in place of the column (#591). Focus follows the swap:
  // the control that made it lands on the one that undoes it, and back.
  const [drawing, setDrawing] = useState(false);
  const drawButtonRef = useRef<HTMLButtonElement | null>(null);
  const backButtonRef = useRef<HTMLButtonElement | null>(null);
  const swapped = useRef(false);
  useEffect(() => {
    if (!swapped.current) return;
    (drawing ? backButtonRef : drawButtonRef).current?.focus();
  }, [drawing]);
  function swapTo(nextDrawing: boolean) {
    swapped.current = true;
    setDrawing(nextDrawing);
  }
  const activePlayers = players.filter((player) => !player.isSpectator);
  const eligiblePlayers = activePlayers.filter((player) => player.connected && !player.isAfk);
  const host = players.find((player) => player.isHost);
  const me = players.find((player) => player.playerId === myPlayerId);
  const canStart = eligiblePlayers.length >= 2;
  const needsPlayers = Math.max(0, 2 - eligiblePlayers.length);
  // The button says how many are missing; the tooltip says what counts, which
  // is the part nobody needs until they wonder why a spectator is not enough.
  const startBlockedReason =
    ui.waitingRoomPanel.spectatorsAfkAndDisconnectedPlayers;
  const rematch = Boolean(finalScores);

  async function copyToClipboard(value: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      notify(ui.waitingRoomPanel.copied({ what }), "success", 2500);
    } catch {
      notify(ui.waitingRoomPanel.couldNotCopy({ what: what.toLowerCase() }), "error");
    }
  }

  // The first three are what everyone wants to know; the rest appear only
  // when the host has moved them off their defaults, which is when they are
  // worth a line. Eight chips said all of it always, and spent 250px doing it.
  // The OS share sheet is how a code actually reaches a group chat on a
  // phone. On a desktop it is the wrong control even where it exists (Safari,
  // Edge): the link is going to be pasted into a chat window beside this
  // one, so the button there just copies it (#580). A phone without a share
  // sheet copies too.
  const offersShare = isNarrow && typeof navigator !== "undefined" && typeof navigator.share === "function";
  async function shareInvite() {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: props.name, text: ui.waitingRoomPanel.joinMySketchyRoomCode({ code: code ?? "" }), url });
        return;
      } catch (error) {
        // A cancelled share is not a failure, and must not fall through to a
        // copy the player did not ask for.
        if ((error as DOMException)?.name === "AbortError") return;
      }
    }
    await copyToClipboard(url, ui.waitingRoomPanel.inviteLink);
  }

  const startButton = (big: boolean) => (
    <button
      type="button"
      className={`btn btn-warm${big ? " btn-big" : ""} waiting-start-button`}
      disabled={!canStart || props.startBusy}
      onClick={props.onStart}
      title={canStart ? undefined : startBlockedReason}
    >
      <PlayIcon size={big ? 17 : 15} />
      {props.startBusy
        ? ui.waitingRoomPanel.starting
        : canStart
          ? rematch ? ui.waitingRoomPanel.rematch : ui.waitingRoomPanel.startGame
          : ui.waitingRoomPanel.needMorePlayers({ count: needsPlayers })}
    </button>
  );
  const waitingForHost = (
    <p className="waiting-start-waiting">
      {host
        ? <>{fill(ui.waitingRoomPanel.hostWillStart({ rematch }), {
        host: (
          <span
            className={playerNameClass(host.isAnonymous)}
            style={playerNameStyle(host.nameColor, host.isAnonymous)}
          >
            {host.nickname}
          </span>
        ),
      })}</>
        : ui.waitingRoomPanel.waitingForAHost}
    </p>
  );
  const drawButton = (
    <button
      ref={drawButtonRef}
      type="button"
      className="btn btn-secondary waiting-draw-button"
      data-testid="open-waiting-pad"
      onClick={() => swapTo(true)}
    >
      <BrushIcon size={15} />
      {ui.scratchPad.drawWhileYouWait}
    </button>
  );

  // Something to do while nobody else is here yet (#591). The first screen a
  // new host reaches is a wait they do not control - the link is in a group
  // chat nobody has opened - and it offered a disabled Start and nothing else.
  // The scratch pad takes the whole column, at a turn's size and with a turn's
  // toolbar, rather than sitting in a card a scroll below Start. What stays is
  // one strip: the way back, the code, and Start - so a second player
  // arriving mid-drawing is one press from a game, not two.
  if (drawing) {
    return (
      <main className="waiting-room is-drawing" data-testid="waiting-room">
        <div className="waiting-pad-strip">
          <button
            ref={backButtonRef}
            type="button"
            className="btn btn-secondary btn-compact waiting-pad-back"
            data-testid="close-waiting-pad"
            onClick={() => swapTo(false)}
          >
            <BackIcon size={15} />
            {ui.scratchPad.backToTheRoom}
          </button>
          {/* Showing the code, copying the invite link, as the header's chip
              used to: the code is what identifies the room at a glance, and
              the link is what somebody pastes into a chat to bring a friend. */}
          {code && (
            <button
              type="button"
              className="room-copy-button waiting-pad-code"
              data-testid="copy-waiting-pad-code"
              title={ui.roomMenuSheet.copyInviteLink}
              onClick={() => void copyToClipboard(window.location.href, ui.waitingRoomPanel.inviteLink)}
            >
              <span className="visually-hidden">{ui.roomMenuSheet.copyInviteLink}: </span>
              <span>{code}</span>
              <CopyIcon size={14} />
            </button>
          )}
          {!isNarrow && (isHost ? startButton(false) : waitingForHost)}
        </div>
        {props.startError && <p className="waiting-start-error">{props.startError}</p>}
        <ScratchPad />
        {/* A phone docks Start at the bottom of the screen, as the room view
            does, rather than wrapping it onto a line of its own in the strip. */}
        {isNarrow && (
          <div className="waiting-rules-footer waiting-start-card" aria-live="polite">
            {isHost ? startButton(true) : waitingForHost}
          </div>
        )}
      </main>
    );
  }

  return (
    <main className="waiting-room" data-testid="waiting-room">
      {/* Which room this is, out of the invite card. It is the one thing on
          the screen that is not about getting people into it. */}
      <header className="waiting-room-head">
        <h1>{props.name}</h1>
        <p className="section-label">
          {props.isPublic ? ui.waitingRoomPanel.publicRoom : ui.waitingRoomPanel.privateRoom} · {rematch ? ui.waitingRoomPanel.betweenGames : ui.waitingRoomPanel.waitingForPlayers}
        </p>
      </header>

      {/* The code, read at a glance or tapped to copy, and one way to send it.
          Six bordered cells and two buttons spent 237px on that. */}
      <section className="waiting-card waiting-invite-card">
        <p className="section-label waiting-invite-kicker">{ui.waitingRoomPanel.inviteYourFriends}</p>
        {code && (
          <p className="waiting-code" aria-label={ui.waitingRoomPanel.roomCodeLabel({ code })}>{code}</p>
        )}
        <div className="waiting-invite-actions">
          {offersShare ? (
            <Button variant="primary" iconLeft={<LinkIcon size={15} />} onClick={() => void shareInvite()}>
              {ui.waitingRoomPanel.shareLink}
            </Button>
          ) : (
            <Button
              variant="primary"
              iconLeft={<LinkIcon size={15} />}
              onClick={() => void copyToClipboard(window.location.href, ui.waitingRoomPanel.inviteLink)}
            >
              {ui.roomMenuSheet.copyInviteLink}
            </Button>
          )}
          {/* A button of its own, not a link pretending to be one: it is the
              other half of the same job as Share, on a card whose whole
              purpose is these two. */}
          <Button
            variant="secondary"
            iconLeft={<CopyIcon size={15} />}
            onClick={() => code && void copyToClipboard(code, ui.waitingRoomPanel.roomCode)}
          >
            {ui.waitingRoomPanel.copyCode}
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
          <h2 id="waiting-roster-title" className="panel-title">{ui.waitingRoomPanel.inTheRoom}</h2>
          <span className="waiting-roster-count">
            {ui.waitingRoomPanel.rosterCount({
              here: activePlayers.length,
              capacity: props.maxPlayers,
            })}
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
                isFriend={friendSeats.has(player.playerId)}
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
                  <span className="visually-hidden">{ui.waitingRoomPanel.you}</span>
                )}
                {player.isHost && <span className="visually-hidden">{ui.waitingRoomPanel.host}</span>}
                {friendSeats.has(player.playerId) && (
                  <span className="visually-hidden">{ui.waitingRoomPanel.friend}</span>
                )}
              </span>
            </li>
          ))}
          {activePlayers.length < props.maxPlayers && (
            <li className="waiting-roster-tile is-empty">
              <span className="waiting-roster-empty-avatar" aria-hidden="true">
                <PlusIcon size={18} />
              </span>
              <span className="waiting-roster-name">{ui.waitingRoomPanel.invite}</span>
            </li>
          )}
        </ul>
      </section>}

      {/* Players get a read-only look at the prompts; the host has the editor
          itself, and spectators are kept away from spoilers. */}
      {props.customPromptCount > 0 && !me?.isSpectator && !isHost && (
        <CustomPromptsPreview count={props.customPromptCount} />
      )}

      {finalScores && (props.highlightCount > 0 || props.drawingCount > 0) && (
        <div className="waiting-room-actions">
          {props.highlightCount > 0 && (
            <Button variant="secondary" onClick={props.onViewHighlights}>
              {ui.waitingRoomPanel.viewHighlights}
            </Button>
          )}
          {props.drawingCount > 0 && (
            <Button variant="secondary" onClick={props.onViewDrawings}>
              {ui.waitingRoomPanel.viewDrawings}
            </Button>
          )}
        </div>
      )}

      {/* The room's rules and the way to start, in one card (#580): the facts
          are what the host checks before pressing Start, so they sit right
          above it. Six cells rather than one line of text, because a line
          said them in a different order and wording from every other place
          a room is described. On a phone the footer docks to the bottom of
          the screen, as Start did - it sat below the fold otherwise. */}
      <section className="waiting-card waiting-rules-card" aria-labelledby="waiting-rules-title">
        <h2 id="waiting-rules-title" className="visually-hidden">{ui.inviteEntryPage.roomRules}</h2>
        <RoomFacts
          testId="waiting-facts"
          room={{
            ...props,
            // Seats, not everybody here: a spectator does not take one.
            playerCount: activePlayers.length,
          }}
        />
        <div className="waiting-rules-footer waiting-start-card" aria-live="polite">
          {isHost ? (
            <>
              <button
                type="button"
                className="btn btn-secondary waiting-rules-edit"
                onClick={() => setSettingsOpen(true)}
              >
                <PencilIcon size={15} />
                {ui.waitingRoomPanel.editRoomRules}
              </button>
              {props.startError && <p className="waiting-start-error">{props.startError}</p>}
              {drawButton}
              {startButton(true)}
            </>
          ) : (
            <>
              {waitingForHost}
              {drawButton}
            </>
          )}
        </div>
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
