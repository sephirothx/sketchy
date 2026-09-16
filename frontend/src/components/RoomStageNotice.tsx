import { useEffect, useRef } from "react";

import { ClockIcon } from "./icons";
import { ScratchPad } from "./ScratchPad";
import { Button } from "./ui/Button";
import { DRAIN_CUE_MS, drainCue, type RoomPauseCause } from "../lib/appNotices";
import { useDrainSecondsLeft } from "../hooks/useServerNotices";
import { useServerNoticesStore, type RoomEndReason } from "../store/serverNoticesStore";
import { ui } from "../content/ui/index.ts";

/**
 * The card over a paused room stage (#823). `roomStage` decides when.
 *
 * While the connection is what is being waited for, the card carries the
 * scratch pad (#829): the seat is held and there is nothing else to do. Not
 * for the other two causes - a server update is ending the game, and a refused
 * rejoin is a decision to make, not a wait.
 */
export function RoomPausedCard({
  cause,
  onReload,
  onLeave,
}: {
  cause: RoomPauseCause;
  onReload: () => void;
  onLeave: () => void;
}) {
  const title =
    cause === "failed" ? ui.roomStageNotice.couldNotRejoin : cause === "server-update" ? ui.roomStageNotice.serverUpdating : ui.roomStageNotice.connectionLost;
  const body =
    cause === "failed"
      ? ui.roomStageNotice.couldNotRejoinDetail
      : cause === "server-update"
        ? ui.roomStageNotice.serverIsUpdating
        : cause === "offline"
          ? ui.roomStageNotice.youReDisconnected
          : ui.roomStageNotice.reconnectingSeatKept;
  const waiting = cause === "offline" || cause === "reconnecting";
  return (
    <div className="room-stage-overlay" data-testid="room-stage-paused" data-cause={cause}>
      <div className={`surface-card room-stage-card${waiting ? " has-scratch-pad" : ""}`}>
        <div role="status" aria-live="polite">
          <h2 className="room-stage-title">{title}</h2>
          <p className="room-stage-body">{body}</p>
        </div>
        {waiting && <ScratchPad />}
        {cause === "failed" && (
          <div className="room-stage-actions">
            <Button variant="secondary" onClick={onLeave}>
              {ui.roomStageNotice.backToLobby}
            </Button>
            <Button variant="primary" onClick={onReload}>
              {ui.app.reload}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** What replaces the stage of a room the server says no longer exists (#823). */
export function RoomEndedCard({ reason, onLeave }: { reason: RoomEndReason; onLeave: () => void }) {
  const actionRef = useRef<HTMLButtonElement | null>(null);
  // The stage the player was using has just been taken away, so focus goes to
  // the one thing left to do rather than falling back to the page.
  useEffect(() => {
    actionRef.current?.focus();
  }, []);
  return (
    <div className="room-ended" data-testid="room-ended" data-reason={reason}>
      <div className="surface-card room-stage-card" role="alert">
        <h2 className="room-stage-title">{ui.roomStageNotice.gameEnded}</h2>
        <p className="room-stage-body">
          {reason === "server-update" ? ui.roomStageNotice.endedServerUpdate : ui.roomStageNotice.endedRoomClosed}
        </p>
        <div className="room-stage-actions">
          <button ref={actionRef} type="button" className="btn btn-primary" onClick={onLeave}>
            {ui.roomStageNotice.backToLobby}
          </button>
        </div>
      </div>
    </div>
  );
}

/** A planned-deploy drain's opening card, on the stage of a live room (#826).

Its own component so the once-a-second countdown re-renders this and not the
room around it. */
export function RoomDrainCue({ playing }: { playing: boolean }) {
  const notice = useServerNoticesStore((state) => state.shutdownNotice);
  const cueSeenFor = useServerNoticesStore((state) => state.drainCueSeenFor);
  const setNotices = useServerNoticesStore((state) => state.set);
  const secondsLeft = useDrainSecondsLeft();
  const startedAt = notice?.startedAt ?? null;
  const cue = drainCue({ drainStartedAt: startedAt, cueSeenFor, secondsLeft, playing });

  // Folds into the header chip by itself: it has said its piece, and the rest
  // of the window is the player's to finish the turn in.
  useEffect(() => {
    if (!cue.card || startedAt === null) return;
    const timer = window.setTimeout(() => setNotices({ drainCueSeenFor: startedAt }), DRAIN_CUE_MS);
    return () => window.clearTimeout(timer);
  }, [cue.card, startedAt, setNotices]);

  if (startedAt === null) return null;
  const dismiss = () => setNotices({ drainCueSeenFor: startedAt });

  if (cue.card) {
    return (
      // A tap anywhere puts it away, so it never stands between somebody and
      // the canvas for longer than they want it to.
      <div
        className="room-stage-overlay is-drain-cue"
        data-testid="room-drain-cue"
        onClick={dismiss}
      >
        <div className="surface-card room-stage-card" onClick={(event) => event.stopPropagation()}>
          <h2 className="room-stage-title">
            <ClockIcon size={18} strokeWidth={2.4} /> {ui.drainCue.title}
          </h2>
          <p className="room-stage-body">
            {playing ? ui.drainCue.gameEndsIn({ seconds: secondsLeft }) : ui.drainCue.noNewGames}
          </p>
          <div className="room-stage-actions">
            <Button variant="primary" onClick={dismiss}>
              {ui.drainCue.gotIt}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

/** The drain's last seconds, pinned to the canvas's top-left corner (#826).

On the canvas rather than across the top of the stage, where it covered the
drawer's prompt and the guessers' letter tiles - the two things somebody needs
most in those seconds. The corner opposite the reaction control is the part of a
drawing least likely to hold anything, and it takes no tap. Mounted only where a
canvas is, which is only while a game is being played. */
export function DrainFinalCountdown() {
  const notice = useServerNoticesStore((state) => state.shutdownNotice);
  const cueSeenFor = useServerNoticesStore((state) => state.drainCueSeenFor);
  const secondsLeft = useDrainSecondsLeft();
  const { finalCountdown } = drainCue({
    drainStartedAt: notice?.startedAt ?? null,
    cueSeenFor,
    secondsLeft,
    playing: true,
  });
  if (!finalCountdown) return null;
  return (
    <div className="canvas-drain-final" data-testid="room-drain-final" aria-hidden="true">
      <ClockIcon size={14} strokeWidth={2.4} />
      {ui.drainCue.finalCountdown({ seconds: secondsLeft })}
    </div>
  );
}
