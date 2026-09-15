import { useEffect, useRef } from "react";

import { Button } from "./ui/Button";
import type { RoomPauseCause } from "../lib/appNotices";
import type { RoomEndReason } from "../store/serverNoticesStore";
import { ui } from "../content/ui/index.ts";

/** The card over a paused room stage (#823). `roomStage` decides when. */
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
  return (
    <div className="room-stage-overlay" data-testid="room-stage-paused" data-cause={cause}>
      <div className="surface-card room-stage-card" role="status" aria-live="polite">
        <h2 className="room-stage-title">{title}</h2>
        <p className="room-stage-body">{body}</p>
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
