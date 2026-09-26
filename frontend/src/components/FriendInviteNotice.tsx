import { useEffect, useLayoutEffect, useRef } from "react";

import { parseFriendInvite } from "../lib/friends";
import { onConnectSpread, socket } from "../lib/socket";
import { useFriendsStore } from "../store/friendsStore";
import { useFriendArrivalNotices } from "../hooks/useFriendArrivalNotices";
import { useFriendInviteAnswer } from "../hooks/useFriendInviteAnswer";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { XIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

/** An invitation from a friend, and the one control that answers it.

Deliberately not a toast. A toast is for something that happened; this asks a
question, and the answer takes a player out of whatever they are doing and into
somebody else's game. It stays until it is answered or it runs out.

The notice holds a token, never a room. Pressing *Join* sends the token back
and the server resolves the room from the sender's seat at that moment — so an
invitation to a game that has since ended fails as one, rather than seating
somebody somewhere stale.

This component always hears the invitation; it draws it only outside a room.
In one, the room bar claims it and shows it as a chip (`RoomNoticeChips`),
because down here it sat on the phone's chat feed and the desktop drawer's
palette (R-UX-07, #1176). */
export function FriendInviteNotice() {
  const receive = useFriendInviteStore((state) => state.receive);
  const clear = useFriendInviteStore((state) => state.clear);
  const inRoomBar = useFriendInviteStore((state) => state.roomBarClaims > 0);
  const { invite, entryPending, join, dismiss } = useFriendInviteAnswer();
  const refreshFriends = useFriendsStore((state) => state.refresh);

  // Sits here because this is the one component mounted app-wide that already
  // owns the friends socket events: the refetch below is what produces the
  // change this speaks about, so the two belong next to each other.
  useFriendArrivalNotices();

  useEffect(() => {
    const onInvite = (payload: unknown) => {
      const parsed = parseFriendInvite(payload);
      if (parsed) receive(parsed);
    };
    // The event stays contentless: one shape covers a request arriving and
    // one being answered, and the endpoint is the truth either way. What
    // happened is worked out from the lists before and after this refetch,
    // and `useFriendArrivalNotices` above says it.
    const onRequest = () => void refreshFriends();
    // And once more whenever the socket comes back. `friends_changed` is a
    // live event with no backlog, so a request that arrived - or one that was
    // accepted - while the connection was down reaches nobody, and the badge
    // and the lists stay wrong until something else happens to move them.
    // Re-reading on connect turns that silence into the ordinary diff, so the
    // notice for it fires late rather than never.
    socket.on("friend_invite_received", onInvite);
    socket.on("friends_changed", onRequest);
    // Spread behind a reconnect for the reason `useEmailStateSync` gives (#872).
    const stopOnConnect = onConnectSpread(onRequest);
    return () => {
      socket.off("friend_invite_received", onInvite);
      socket.off("friends_changed", onRequest);
      stopOnConnect();
    };
  }, [refreshFriends, receive]);

  // The server forgets it at the same moment, so a notice that outlived its
  // token would offer a button that cannot work - whichever of the two homes
  // is drawing it, so the timer lives here, where the invitation arrives.
  const stored = useFriendInviteStore((state) => state.invite);
  useEffect(() => {
    if (!stored) return;
    const timer = window.setTimeout(() => {
      if (useFriendInviteStore.getState().invite === stored) clear();
    }, stored.expiresIn * 1000);
    return () => window.clearTimeout(timer);
  }, [stored, clear]);

  // The toasts sit in the same bottom-centre spot, and this component is also
  // what announces friend requests - which landed on the card's own Join.
  // So while the card is up it publishes how far it reaches above the page's
  // dock (which it stands on itself), and the toast stack stands on both
  // (R-UX-07). The card stays out of the stack: it is a question, not
  // something that happened.
  const cardRef = useRef<HTMLDivElement | null>(null);
  const shown = invite !== null && !inRoomBar;
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!shown || !card) return;
    const root = document.documentElement;
    const publish = () => {
      // Its offset less the dock's, read together: the part that is the
      // card's own, which does not change when the dock does.
      const bottom = Number.parseFloat(getComputedStyle(card).bottom) || 0;
      const dock = Number.parseFloat(getComputedStyle(root).getPropertyValue("--dock-clearance")) || 0;
      root.style.setProperty("--friend-invite-clearance", `${bottom - dock + card.offsetHeight}px`);
    };
    publish();
    // A long name wraps the card to a second line on a phone.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(card);
    return () => {
      observer?.disconnect();
      root.style.setProperty("--friend-invite-clearance", "0px");
    };
  }, [shown]);

  // Said once when it arrives, whichever home draws it, from here rather than
  // from either home: the room bar is not rendered at all while a phone's
  // guess keyboard is up, so a region in it said nothing to exactly the
  // player most likely to be mid-turn, and moving between the card and the
  // chip would have said it again. Mounted for good, so it is there before
  // the words are.
  const announcer = (
    <span className="visually-hidden" role="status" aria-live="polite" data-testid="friend-invite-announcer">
      {invite ? `${invite.displayName} ${ui.friendInviteNotice.invitedYouTheirGame}` : ""}
    </span>
  );

  if (!invite || inRoomBar) return announcer;

  return (
    <>
      {announcer}
      <div ref={cardRef} className="friend-invite-notice" data-testid="friend-invite">
        <span className="friend-invite-text">
          <strong>{invite.displayName}</strong> {ui.friendInviteNotice.invitedYouTheirGame}
        </span>
        <button
          type="button"
          className="btn btn-primary btn-compact"
          disabled={entryPending}
          onClick={() => void join()}
        >
          {ui.friendInviteNotice.join}
        </button>
        <button
          type="button"
          className="btn btn-icon friend-invite-dismiss"
          aria-label={ui.friendInviteNotice.dismissInvitation}
          onClick={dismiss}
        >
          <XIcon size={14} />
        </button>
      </div>
    </>
  );
}
