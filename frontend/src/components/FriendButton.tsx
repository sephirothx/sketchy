import { useFriendsStore } from "../store/friendsStore";
import type { FriendAction } from "../lib/friends";
import { Button } from "./ui/Button";
import { PlusIcon } from "./icons";

/** The one control for "become friends with this person".

Shared by the profile page and the recent-players list so that the four states
a friendship can be in look and behave the same wherever they are read. The
lobby's row is deliberately not this: it is an icon in a dense list with a
presence status beside it, and squeezing both into one component made each
worse.

`friends` and `none` render nothing. Ending a friendship belongs on the
friends surface, where it is confirmed first (R-FRIEND-10) — a Remove button
sitting on somebody's profile is one mis-click away from revoking a way into a
game. */
export function FriendButton({
  action,
  userId,
  displayName,
}: {
  action: FriendAction;
  userId: string;
  displayName: string;
}) {
  const pending = useFriendsStore((state) => state.pending);
  const add = useFriendsStore((state) => state.add);
  const accept = useFriendsStore((state) => state.accept);
  const busy = pending === userId;

  if (action === "add") {
    return (
      <Button
        variant="secondary"
        compact
        disabled={busy}
        iconLeft={<PlusIcon size={14} />}
        onClick={() => void add(userId)}
      >
        Add friend
      </Button>
    );
  }
  if (action === "accept") {
    return (
      <Button
        variant="primary"
        compact
        disabled={busy}
        onClick={() => void accept(userId)}
      >
        Accept request
      </Button>
    );
  }
  if (action === "sent") {
    // A statement rather than a control. Withdrawing is on the friends
    // surface, beside the rest of what was sent.
    return (
      <span className="friend-button-status" aria-label={`Friend request sent to ${displayName}`}>
        Request sent
      </span>
    );
  }
  return null;
}
