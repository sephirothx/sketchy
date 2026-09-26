import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { ClockIcon, MailIcon, WifiOffIcon } from "./icons";
import { DRAIN_FINAL_SECONDS, placeNotices, type ChipNotice } from "../lib/appNotices";
import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";
import { useDrainSecondsLeft } from "../hooks/useServerNotices";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { useFriendInviteAnswer } from "../hooks/useFriendInviteAnswer";
import { ui } from "../content/ui/index.ts";

function connectionLabel(status: Exclude<ConnectionStatus, "connected">): string {
  // "Disconnected", never "offline": the glossary's word for a dropped
  // connection (R-UX-02).
  if (status === "offline") return ui.roomNoticeChips.disconnected;
  if (status === "failed") return ui.roomNoticeChips.rejoinFailed;
  return ui.roomNoticeChips.reconnecting;
}

/** A chip in the room bar: a server notice, or a friend's invitation. */
type RoomChip = ChipNotice | "invite";

/** A planned-deploy drain, a dropped connection and a friend's invitation, as
chips in the room header.

A room lays itself out to the viewport (R-UX-01), so a banner there is height
taken off the canvas - and, on a phone, it used to sit on top of this very
header and take its taps. These two are the notices that happen mid-game, so
they live where the round and the countdown already are, and the full sentence
is one tap away (R-UX-07). Everything else is `AppBanners`'.

A friend's **Invitation** is the third, on every width. Outside a room it is a
card at the bottom of the screen (`FriendInviteNotice`), and in a room that
spot is the phone's chat feed and the desktop drawer's palette: it hid the
latest guesses and the colours (#1176). Here it is one tap from its Join and
its Not now, and the card steps aside for as long as this bar is mounted.

Every chip always renders its word. On a phone the bar decides whether it
shows: the band is a phone's width and already holds the round, the ring, the
menu and the avatar, so once the round's word and the wordmark have gone the
chips keep their icons alone (`useRoomBarGiveWay`, R-UX-11). Their accessible
names are their `aria-label`s, so hiding the word takes nothing from them. */
export function RoomNoticeChips() {
  const shutdownNotice = useServerNoticesStore((state) => state.shutdownNotice);
  const updateRequired = useServerNoticesStore((state) => state.updateRequired);
  const connection = useServerNoticesStore((state) => state.connection);
  const secondsLeft = useDrainSecondsLeft();
  const [open, setOpen] = useState<RoomChip | null>(null);
  const { invite, entryPending, join, dismiss } = useFriendInviteAnswer();
  const claimRoomBar = useFriendInviteStore((state) => state.claimRoomBar);
  // Before paint, so the card never shows for a frame over the room.
  useLayoutEffect(() => claimRoomBar(), [claimRoomBar]);
  const groupRef = useRef<HTMLDivElement | null>(null);
  const popoverId = useId();

  const { chips: serverChips } = placeNotices({
    inRoom: true,
    updateRequired,
    // Neither is ever raised inside a room, and a chip is not their home.
    serverFull: false,
    restarted: false,
    // A pause does not touch a game already running.
    paused: false,
    draining: shutdownNotice !== null,
    connection,
  });
  // Last: a question for later, where the other two are about this game.
  const chips: RoomChip[] = invite ? [...serverChips, "invite"] : serverChips;
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
  // The card's own sentence, name first as it reads there.
  const inviteText = invite ? `${invite.displayName} ${ui.friendInviteNotice.invitedYouTheirGame}` : "";

  return (
    <div className="room-notice-chips" ref={groupRef}>
      {chips.map((notice) => {
        const isDrain = notice === "drain";
        const isInvite = notice === "invite";
        const full = isInvite
          ? inviteText
          : isDrain ? drainText : connectionTrouble ? connectionStatusText(connectionTrouble) : "";
        const label = isInvite
          ? ui.roomNoticeChips.invitation
          : isDrain
            ? ui.roomNoticeChips.serverUpdate({ seconds: secondsLeft })
            : connectionTrouble ? connectionLabel(connectionTrouble) : "";
        // Red for the drain's last seconds, when the stage says it too (#826).
        const finalStretch = secondsLeft > 0 && secondsLeft <= DRAIN_FINAL_SECONDS;
        const tone = isInvite
          ? "primary"
          : isDrain
            ? finalStretch ? "danger" : "warm"
            : connection === "reconnecting" ? "warning" : "danger";
        return (
          <button
            key={notice}
            type="button"
            className={`chip chip-${tone} room-notice-chip`}
            data-notice={notice}
            // The invitation's visible word leads its name, so saying the
            // label the chip shows reaches it (WCAG 2.5.3).
            aria-label={isInvite ? `${label}: ${full}` : full}
            aria-expanded={openNotice === notice}
            aria-controls={openNotice === notice ? popoverId : undefined}
            onClick={() => setOpen((current) => (current === notice ? null : notice))}
          >
            {isInvite ? (
              <MailIcon size={13} strokeWidth={2.4} />
            ) : isDrain ? (
              <ClockIcon size={13} strokeWidth={2.4} />
            ) : (
              <WifiOffIcon size={13} strokeWidth={2.4} />
            )}
            <span className="room-notice-chip-label">{label}</span>
          </button>
        );
      })}
      {openNotice === "invite" && invite && (
        <div id={popoverId} className="room-notice-popover" data-notice="invite">
          <p>
            <strong>{invite.displayName}</strong> {ui.friendInviteNotice.invitedYouTheirGame}
          </p>
          <div className="room-notice-popover-actions">
            <button
              type="button"
              className="btn btn-primary btn-compact"
              disabled={entryPending}
              onClick={() => void join()}
            >
              {ui.friendInviteNotice.join}
            </button>
            <button type="button" className="btn btn-secondary btn-compact" onClick={dismiss}>
              {ui.friendInviteNotice.notNow}
            </button>
          </div>
        </div>
      )}
      {openNotice !== null && openNotice !== "invite" && (
        <div id={popoverId} className="room-notice-popover" data-notice={openNotice}>
          <p>{openNotice === "drain" ? drainText : connectionTrouble ? connectionStatusText(connectionTrouble) : null}</p>
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
