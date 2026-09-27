import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { ClockIcon, MailIcon, UsersIcon, WifiOffIcon } from "./icons";
import { DRAIN_FINAL_SECONDS, placeNotices, type ChipNotice } from "../lib/appNotices";
import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";
import { useDrainSecondsLeft } from "../hooks/useServerNotices";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { useFriendInviteAnswer } from "../hooks/useFriendInviteAnswer";
import { useFriendRequestNoticeStore } from "../store/friendRequestNoticeStore";
import { useFriendsStore } from "../store/friendsStore";
import { useOpenOverlay } from "../hooks/useOverlayRoute";
import { FRIENDS_PATH } from "../lib/overlayRoutes";
import { friendRequestSentence, stillWaiting } from "../lib/friends";
import { ui } from "../content/ui/index.ts";

/** "*Ada* wants to be friends.", with the name in bold wherever the
    language puts it: the sentence is formatted around a placeholder and split
    there, so no catalogue has to be written in two halves. */
function AskerSentence({ name }: { name: string }) {
  const MARK = "\u0000";
  const [before, after = ""] = ui.useFriendArrivalNotices.wantsToBeFriends({ name: MARK }).split(MARK);
  return (
    <>
      {before}
      <strong>{name}</strong>
      {after}
    </>
  );
}

function connectionLabel(status: Exclude<ConnectionStatus, "connected">): string {
  // "Disconnected", never "offline": the glossary's word for a dropped
  // connection (R-UX-02).
  if (status === "offline") return ui.roomNoticeChips.disconnected;
  if (status === "failed") return ui.roomNoticeChips.rejoinFailed;
  return ui.roomNoticeChips.reconnecting;
}

/** A chip in the room bar: a server notice, a friend's invitation, or a
    friend request. */
type RoomChip = ChipNotice | "invite" | "friend-request";

/** A planned-deploy drain, a dropped connection, a friend's invitation and a
friend request, as chips in the room header.

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

A **Friend request** is the fourth, for the same reason: its toast stood on the
same spot (#1197). Its popover says who asked, with *Accept* - or *Open*, the
friends surface, when several did - and *Not now*, which only puts the chip
away. There is no Decline here: a refusal is kept, so it is answered on the
friends surface behind its confirmation (R-FRIEND-05, R-FRIEND-10). The chip
lasts while the request waits, so an answer given anywhere else takes it down.

Every chip always renders its word. On a phone the bar decides whether it
shows: the band is a phone's width and already holds the round, the ring, the
menu and the avatar, so once the round's word and the wordmark have gone the
chips keep their icons alone - the drain its countdown too, which goes only if
the bar takes a second row (`useRoomBarGiveWay`, R-UX-11). Their accessible
names are their `aria-label`s, so hiding the word takes nothing from them. */
export function RoomNoticeChips() {
  const shutdownNotice = useServerNoticesStore((state) => state.shutdownNotice);
  const updateRequired = useServerNoticesStore((state) => state.updateRequired);
  const connection = useServerNoticesStore((state) => state.connection);
  const secondsLeft = useDrainSecondsLeft();
  const [open, setOpen] = useState<RoomChip | null>(null);
  const { invite, entryPending, join, dismiss } = useFriendInviteAnswer();
  const claimRoomBar = useFriendInviteStore((state) => state.claimRoomBar);
  const namedRequests = useFriendRequestNoticeStore((state) => state.askers);
  const putOffRequests = useFriendRequestNoticeStore((state) => state.clear);
  const incoming = useFriendsStore((state) => state.lists.incoming);
  const accept = useFriendsStore((state) => state.accept);
  const friendsBusy = useFriendsStore((state) => state.pending !== null);
  const openOverlay = useOpenOverlay();
  // Only those still waiting: answered anywhere, a request leaves the chip.
  const requests = stillWaiting(namedRequests, incoming);
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
  // Last: questions for later, where the other two are about this game - the
  // invitation first, since it runs out and a request does not.
  const chips: RoomChip[] = [
    ...serverChips,
    ...(invite ? ["invite" as const] : []),
    ...(requests.length > 0 ? ["friend-request" as const] : []),
  ];
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
  const requestText = requests.length > 0 ? friendRequestSentence(requests) : "";

  return (
    <div className="room-notice-chips" ref={groupRef}>
      {chips.map((notice) => {
        const isDrain = notice === "drain";
        const isInvite = notice === "invite";
        const isRequest = notice === "friend-request";
        // A question for later: named by the word it shows, then its sentence.
        const isQuestion = isInvite || isRequest;
        const full = isInvite
          ? inviteText
          : isRequest
            ? requestText
            : isDrain ? drainText : connectionTrouble ? connectionStatusText(connectionTrouble) : "";
        const label = isInvite
          ? ui.roomNoticeChips.invitation
          : isRequest
            ? ui.roomNoticeChips.friendRequest({ count: requests.length })
            : isDrain
              ? ui.roomNoticeChips.serverUpdateWord
              : connectionTrouble ? connectionLabel(connectionTrouble) : "";
        // Red for the drain's last seconds, when the stage says it too (#826).
        const finalStretch = secondsLeft > 0 && secondsLeft <= DRAIN_FINAL_SECONDS;
        const tone = isQuestion
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
            // A question's visible word leads its name, so saying the label
            // the chip shows reaches it (WCAG 2.5.3).
            aria-label={isQuestion ? `${label}: ${full}` : full}
            aria-expanded={openNotice === notice}
            aria-controls={openNotice === notice ? popoverId : undefined}
            onClick={() => setOpen((current) => (current === notice ? null : notice))}
          >
            {isInvite ? (
              <MailIcon size={13} strokeWidth={2.4} />
            ) : isRequest ? (
              <UsersIcon size={13} strokeWidth={2.4} />
            ) : isDrain ? (
              <ClockIcon size={13} strokeWidth={2.4} />
            ) : (
              <WifiOffIcon size={13} strokeWidth={2.4} />
            )}
            <span className="room-notice-chip-label">{label}</span>
            {/* The drain's countdown is its own span: the bar may take the
                chip's word, never its seconds, until it takes a second row
                (#806, R-UX-11). */}
            {isDrain && (
              <span className="room-notice-chip-seconds">
                {ui.roomNoticeChips.serverUpdateSeconds({ seconds: secondsLeft })}
              </span>
            )}
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
      {openNotice === "friend-request" && requests.length > 0 && (
        <div id={popoverId} className="room-notice-popover" data-notice="friend-request">
          {/* One asker is named in bold, as the invitation's sender is. */}
          <p>{requests.length === 1 ? <AskerSentence name={requests[0].displayName} /> : requestText}</p>
          <div className="room-notice-popover-actions">
            {requests.length === 1 ? (
              <button
                type="button"
                className="btn btn-primary btn-compact"
                disabled={friendsBusy}
                onClick={() => void accept(requests[0].userId)}
              >
                {ui.useFriendArrivalNotices.accept}
              </button>
            ) : (
              // One button cannot mean four people: the surface answers a list.
              <button
                type="button"
                className="btn btn-primary btn-compact"
                onClick={() => {
                  putOffRequests();
                  openOverlay(FRIENDS_PATH);
                }}
              >
                {ui.useFriendArrivalNotices.open}
              </button>
            )}
            {/* Sends nothing: the request still waits on the friends surface,
                under its badge, and nobody is told it was put off. */}
            <button type="button" className="btn btn-secondary btn-compact" onClick={putOffRequests}>
              {ui.friendInviteNotice.notNow}
            </button>
          </div>
        </div>
      )}
      {openNotice !== null && openNotice !== "invite" && openNotice !== "friend-request" && (
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
