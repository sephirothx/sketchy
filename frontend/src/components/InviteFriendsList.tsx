import { useMemo, useState } from "react";

import { emitWithAck } from "../lib/socket";
import { useToast } from "../lib/toast";
import { useFriendsStore } from "../store/friendsStore";
import { usePresenceStore } from "../store/presenceStore";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";

/** Friends who are online, on the card whose whole job is getting people in.

The other half of *Share the link*. Sharing a code is the only way in that has
ever existed, and it works on anybody — but for the people you actually play
with, it is a clipboard round trip through another app. This is the same
gesture without leaving the room.

Only friends already in a game are left out: they are somewhere else, and an
invitation would be asking them to abandon it. Everybody else is shown whether
or not they are looking at the lobby, because the notice reaches an account
wherever it is. */
export function InviteFriendsList() {
  const lists = useFriendsStore((state) => state.lists);
  const presence = usePresenceStore((state) => state.presence);
  const { notify } = useToast();
  const [invited, setInvited] = useState<Set<string>>(new Set());
  const [sending, setSending] = useState<string | null>(null);

  const invitable = useMemo(() => {
    const online = new Map(presence.players.map((p) => [p.userId, p]));
    return lists.friends
      .map((friend) => ({ friend, presence: online.get(friend.userId) }))
      .filter(({ presence: p }) => p !== undefined && p.status === "lobby");
  }, [lists.friends, presence.players]);

  if (invitable.length === 0) return null;

  async function invite(userId: string, displayName: string) {
    if (sending) return;
    setSending(userId);
    try {
      const answer = await emitWithAck<{ ok: boolean; error?: string }>(
        "invite_friend",
        { friendUserId: userId },
      );
      if (answer?.ok) {
        setInvited((current) => new Set(current).add(userId));
        notify(`Invitation sent to ${displayName}.`);
      } else {
        notify(answer?.error ?? "That invitation could not be sent.");
      }
    } catch {
      notify("That invitation could not be sent.");
    } finally {
      setSending(null);
    }
  }

  return (
    <div className="waiting-invite-friends">
      <p className="waiting-invite-friends-label">Friends in the lobby</p>
      <ul className="waiting-invite-friends-list" data-testid="invite-friends">
        {invitable.map(({ friend }) => (
          <li key={friend.userId}>
            <Avatar
              name={friend.displayName}
              nameColor={friend.nameColor ?? undefined}
              avatarUrl={friend.avatarUrl}
              isAnonymous={friend.isAnonymous}
              size={26}
            />
            <span className="waiting-invite-friend-name">{friend.displayName}</span>
            {invited.has(friend.userId) ? (
              <span className="waiting-invite-friend-sent">Invited</span>
            ) : (
              <Button
                variant="secondary"
                compact
                disabled={sending === friend.userId}
                onClick={() => void invite(friend.userId, friend.displayName)}
              >
                Invite
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
