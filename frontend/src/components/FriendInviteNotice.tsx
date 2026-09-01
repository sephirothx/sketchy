import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { parseFriendInvite, type FriendInvite } from "../lib/friends";
import { sessionFrom } from "../lib/roomEntryState";
import { emitWithAck, socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { useGameStore } from "../store/gameStore";
import { useToast } from "../lib/toast";
import { XIcon } from "./icons";
import type { AckResponse } from "../types";

/** An invitation from a friend, and the one control that answers it.

Deliberately not a toast. A toast is for something that happened; this asks a
question, and the answer takes a player out of whatever they are doing and into
somebody else's game. It stays until it is answered or it runs out.

The notice holds a token, never a room. Pressing *Join* sends the token back
and the server resolves the room from the sender's seat at that moment — so an
invitation to a game that has since ended fails as one, rather than seating
somebody somewhere stale. */
export function FriendInviteNotice() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [invite, setInvite] = useState<FriendInvite | null>(null);
  const refreshFriends = useFriendsStore((state) => state.refresh);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);
  const setSession = useGameStore((state) => state.setSession);

  useEffect(() => {
    const onInvite = (payload: unknown) => {
      const parsed = parseFriendInvite(payload);
      if (parsed) setInvite(parsed);
    };
    // A request needs no notice of its own — the lobby list is where it is
    // answered — but the list has to know it arrived.
    const onRequest = () => void refreshFriends();
    socket.on("friend_invite_received", onInvite);
    socket.on("friend_request_received", onRequest);
    return () => {
      socket.off("friend_invite_received", onInvite);
      socket.off("friend_request_received", onRequest);
    };
  }, [refreshFriends]);

  // The server forgets it at the same moment, so a notice that outlived its
  // token would offer a button that cannot work.
  useEffect(() => {
    if (!invite) return;
    const timer = window.setTimeout(
      () => setInvite(null),
      invite.expiresIn * 1000,
    );
    return () => window.clearTimeout(timer);
  }, [invite]);

  // Signing out mid-invitation leaves a notice addressed to nobody. Derived
  // rather than cleared in an effect: the token is the server's to expire, and
  // there is nothing to tidy up here beyond not drawing it.
  if (!invite || !myUserId) return null;

  async function join() {
    const current = invite;
    if (!current) return;
    setInvite(null);
    try {
      const answer = await emitWithAck<AckResponse>("join_friend_room", {
        friendUserId: current.fromUserId,
        inviteToken: current.inviteToken,
      });
      const session = sessionFrom(answer);
      if (!session) {
        notify(answer?.error ?? "That game could not be joined.");
        return;
      }
      setSession(session);
      navigate(`/room/${session.code}`);
    } catch {
      notify("That game could not be joined.");
    }
  }

  return (
    <div className="friend-invite-notice" role="status" data-testid="friend-invite">
      <span className="friend-invite-text">
        <strong>{invite.displayName}</strong> invited you to their game.
      </span>
      <button type="button" className="btn btn-primary btn-compact" onClick={() => void join()}>
        Join
      </button>
      <button
        type="button"
        className="btn btn-icon friend-invite-dismiss"
        aria-label="Dismiss invitation"
        onClick={() => setInvite(null)}
      >
        <XIcon size={14} />
      </button>
    </div>
  );
}
