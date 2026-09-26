import { useNavigate } from "react-router-dom";

import { sessionFrom } from "../lib/roomEntryState";
import { emitEntry } from "../lib/socket";
import { useToast } from "../lib/toast";
import { refusalText } from "../lib/refusals.ts";
import { useAuthStore } from "../store/authStore";
import { useFriendInviteStore } from "../store/friendInviteStore";
import { useGameStore } from "../store/gameStore";
import { useRoomEntryStore } from "../store/roomEntryStore";
import type { AckResponse } from "../types";
import { ui } from "../content/ui/index.ts";

/** The waiting invitation, and the two answers to it.

Shared by the two places an invitation is drawn - the card outside a room and
the room bar's chip inside one (R-UX-07) - so Join behaves the same from
either: the same entry lock, the same refusal, the same route. */
export function useFriendInviteAnswer() {
  const navigate = useNavigate();
  const { notify } = useToast();
  const stored = useFriendInviteStore((state) => state.invite);
  const clear = useFriendInviteStore((state) => state.clear);
  const myUserId = useAuthStore((state) => state.user?.id ?? null);
  const setSession = useGameStore((state) => state.setSession);
  const entryPending = useRoomEntryStore((state) => state.pending !== null);

  // Signing out mid-invitation leaves a notice addressed to nobody. Derived
  // rather than cleared in an effect: the token is the server's to expire, and
  // there is nothing to tidy up here beyond not drawing it.
  const invite = myUserId === null ? null : stored;

  async function join() {
    const current = invite;
    if (!current) return;
    // Mounted above every page, so it is the one way in that the lobby's own
    // controls cannot see: it takes the same lock they do, and while another
    // entry holds it the notice waits rather than racing it for the seat.
    const token = useRoomEntryStore.getState().begin("friend-invite");
    if (token === null) return;
    clear();
    try {
      const answer = await emitEntry<AckResponse>("join_friend_room", {
        friendUserId: current.fromUserId,
        inviteToken: current.inviteToken,
      });
      const session = sessionFrom(answer);
      if (!session) {
        notify(refusalText(answer, ui.friendInviteNotice.couldNotJoinThatGame), "error");
        return;
      }
      setSession(session);
      navigate(`/room/${session.code}`);
    } catch {
      notify(ui.friendInviteNotice.couldNotJoinThatGame, "error");
    } finally {
      useRoomEntryStore.getState().end(token);
    }
  }

  return { invite, entryPending, join, dismiss: clear };
}
