import { useEffect, useId, useRef, useState } from "react";

import { AlertIcon, ClockIcon, WifiOffIcon } from "./icons";
import { DRAIN_FINAL_SECONDS, placeNotices, type ChipNotice } from "../lib/appNotices";
import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";
import { useDrainSecondsLeft } from "../hooks/useServerNotices";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { useCanvasReadbackStore } from "../store/canvasReadbackStore";
import { ui } from "../content/ui/index.ts";

function connectionLabel(status: Exclude<ConnectionStatus, "connected">): string {
  // "Disconnected", never "offline": the glossary's word for a dropped
  // connection (R-UX-02).
  if (status === "offline") return ui.roomNoticeChips.disconnected;
  if (status === "failed") return ui.roomNoticeChips.rejoinFailed;
  return ui.roomNoticeChips.reconnecting;
}

/** A planned-deploy drain, a dropped connection and a blocked canvas, as chips in the room header.

A room lays itself out to the viewport (R-UX-01), so a banner there is height
taken off the canvas - and, on a phone, it used to sit on top of this very
header and take its taps. These two are the notices that happen mid-game, so
they live where the round and the countdown already are, and the full sentence
is one tap away (R-UX-07). A **Canvas blocked** notice is about the canvas
right below, so in a room it is a chip too, with the way to check again in its
card (R-UX-15). Everything else is `AppBanners`'.

On a phone the chip takes the place of the room code (which is also in the ⋯
sheet) and of the mark, and a second chip shows only its icon: the band is a
390px screen's width and already holds the round, the ring and the menu. */
export function RoomNoticeChips({ compact }: { compact: boolean }) {
  const shutdownNotice = useServerNoticesStore((state) => state.shutdownNotice);
  const updateRequired = useServerNoticesStore((state) => state.updateRequired);
  const connection = useServerNoticesStore((state) => state.connection);
  const secondsLeft = useDrainSecondsLeft();
  const canvasBlocked = useCanvasReadbackStore((state) => state.status === "tampered");
  const checkCanvas = useCanvasReadbackStore((state) => state.check);
  const [open, setOpen] = useState<ChipNotice | null>(null);
  const groupRef = useRef<HTMLDivElement | null>(null);
  const popoverId = useId();

  const { chips } = placeNotices({
    inRoom: true,
    updateRequired,
    // Neither is ever raised inside a room, and a chip is not their home.
    serverFull: false,
    restarted: false,
    // A pause does not touch a game already running.
    paused: false,
    draining: shutdownNotice !== null,
    connection,
    canvasBlocked,
  });
  // A notice that ends closes its own popover rather than leaving a card that
  // describes something no longer true - and closes it for good: only hiding
  // it kept the choice, so the next outage opened the card nobody asked for.
  if (open !== null && !chips.includes(open)) setOpen(null);
  const openNotice = open !== null && chips.includes(open) ? open : null;

  useEffect(() => {
    if (openNotice === null) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!groupRef.current?.contains(event.target as Node)) setOpen(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openNotice]);

  const drainText = ui.app.serverUpdateInProgress({ seconds: secondsLeft });
  const connectionTrouble = connection === "connected" ? null : connection;
  const canvasText = `${ui.app.canvasBlocked} ${ui.app.canvasBlockedFix}`;
  const fullText = (notice: ChipNotice): string => {
    if (notice === "drain") return drainText;
    if (notice === "canvas-blocked") return canvasText;
    return connectionTrouble ? connectionStatusText(connectionTrouble) : "";
  };

  return (
    <div className="room-notice-chips" ref={groupRef}>
      {chips.map((notice) => {
        const isDrain = notice === "drain";
        const isCanvas = notice === "canvas-blocked";
        const full = fullText(notice);
        const label = isDrain
          ? ui.roomNoticeChips.serverUpdate({ seconds: secondsLeft })
          : isCanvas ? ui.roomNoticeChips.canvasBlocked
          : connectionTrouble ? connectionLabel(connectionTrouble) : "";
        const iconOnly = compact && !isDrain && chips.length > 1;
        // Red for the drain's last seconds, when the stage says it too (#826).
        const finalStretch = secondsLeft > 0 && secondsLeft <= DRAIN_FINAL_SECONDS;
        const tone = isDrain
          ? finalStretch ? "danger" : "warm"
          : isCanvas || connection === "reconnecting" ? "warning" : "danger";
        return (
          <button
            key={notice}
            type="button"
            className={`chip chip-${tone} room-notice-chip`}
            data-notice={notice}
            aria-label={full}
            aria-expanded={openNotice === notice}
            aria-controls={openNotice === notice ? popoverId : undefined}
            onClick={() => setOpen((current) => (current === notice ? null : notice))}
          >
            {isDrain
              ? <ClockIcon size={13} strokeWidth={2.4} />
              : isCanvas ? <AlertIcon size={13} strokeWidth={2.4} /> : <WifiOffIcon size={13} strokeWidth={2.4} />}
            {!iconOnly && <span className="room-notice-chip-label">{label}</span>}
          </button>
        );
      })}
      {openNotice !== null && (
        <div id={popoverId} className="room-notice-popover" data-notice={openNotice}>
          <p>{fullText(openNotice)}</p>
          {openNotice === "canvas-blocked" && (
            <button type="button" className="btn btn-secondary btn-compact" onClick={() => checkCanvas()}>
              {ui.app.checkAgain}
            </button>
          )}
          {openNotice === "connection" && connection === "failed" && (
            <button type="button" className="btn btn-secondary btn-compact" onClick={() => window.location.reload()}>
              {ui.app.reload}
            </button>
          )}
        </div>
      )}
      {/* Announced once when a drain begins, not every second the chip's
          countdown moves: the chip's own name carries the live sentence for
          anybody who goes looking. A lost connection is announced by the card
          that pauses the stage (RoomStageNotice), so it is not said twice. */}
      <span className="visually-hidden" role="status" aria-live="polite">
        {chips.includes("drain") ? ui.roomNoticeChips.serverUpdateStarted : ""}
      </span>
    </div>
  );
}
