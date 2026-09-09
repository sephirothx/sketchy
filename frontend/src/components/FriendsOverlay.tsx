import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import {
  friendsSurface,
  friendsSurfaceIsEmpty,
  type FriendEntry,
} from "../lib/friends";
import { useCloseOverlay } from "../hooks/useOverlayRoute";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { ConfirmationDialog } from "./ConfirmationDialog";
import { UsersIcon, XIcon } from "./icons";

/** Friends, everywhere and whether or not they are online (R-FRIEND-10).

An overlay on a route, for the same two reasons Settings is one (R-SET-06): it
can be linked, and it draws over the page it was opened from, so a request that
arrives mid-game can be answered without giving up a seat.

The lobby's *Who is online* panel is not this. That answers "who is around",
which is why it is a presence list with friends sorted to the top; this answers
"who are my friends and what is waiting", which is a different question and has
no online/offline in it at all.

**An outgoing request that disappears is a decline, and that is not hidden.**
A sender who may withdraw a request has to be able to see it, so the row exists
and its going away is legible. R-FRIEND-05 is about the endpoint's *answer* -
the POST says the same thing whether it landed, hit a block or hit an earlier
refusal - not about concealing the list forever after. Nothing here narrates
the disappearance; it simply does not pretend the row is still pending. */

type Confirming =
  | { kind: "decline"; entry: FriendEntry }
  | { kind: "unfriend"; entry: FriendEntry }
  | null;

export function FriendsOverlay() {
  const close = useCloseOverlay();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();

  const isGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  const lists = useFriendsStore((state) => state.lists);
  const loaded = useFriendsStore((state) => state.loaded);
  const pending = useFriendsStore((state) => state.pending);
  const refresh = useFriendsStore((state) => state.refresh);
  const accept = useFriendsStore((state) => state.accept);
  const remove = useFriendsStore((state) => state.remove);
  const [confirming, setConfirming] = useState<Confirming>(null);

  // Opened from a menu that may have been sitting there a while, and the lists
  // move without this screen being on. Cheap, and the alternative is a stale
  // Accept button for a request that has already been withdrawn.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useFocusTrap(dialogRef, { onEscape: close, initialFocusRef: closeButtonRef });

  const surface = useMemo(() => friendsSurface(lists), [lists]);

  return (
    <div
      className="modal-overlay friends-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card friends-modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="friends"
      >
        <div className="friends-modal-header">
          <h3 id={titleId}>
            <UsersIcon size={20} />
            <span>Friends</span>
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            className="close-icon-button"
            onClick={close}
            title="Close"
            aria-label="Close friends"
          >
            <XIcon size={16} />
          </button>
        </div>

        <div className="friends-modal-body">
          {/* A guest reaching this by URL. The menu does not offer it to them,
              and the endpoint answers 403, so the honest screen says why
              rather than showing an empty list that looks like a fault. */}
          {isGuest ? (
            <p className="friends-empty">
              Friends need an account. A guest name belongs to this browser
              rather than to you, so there would be nobody left to be friends
              with a month from now.
            </p>
          ) : !loaded ? (
            <p className="friends-empty">Loading…</p>
          ) : friendsSurfaceIsEmpty(surface) ? (
            <p className="friends-empty">
              No friends yet. Add somebody from the lobby, or from a game you
              are both in.
            </p>
          ) : (
            <>
              <FriendsSection
                title="Requests"
                count={surface.incoming.length}
                entries={surface.incoming}
                testId="friends-incoming"
                renderActions={(entry) => (
                  <>
                    <Button
                      variant="primary"
                      compact
                      disabled={pending === entry.userId}
                      onClick={() => void accept(entry.userId)}
                    >
                      Accept
                    </Button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-compact"
                      disabled={pending === entry.userId}
                      onClick={() => setConfirming({ kind: "decline", entry })}
                    >
                      Decline
                    </button>
                  </>
                )}
              />
              <FriendsSection
                title="Sent"
                count={surface.outgoing.length}
                entries={surface.outgoing}
                testId="friends-outgoing"
                renderActions={(entry) => (
                  // No confirmation: cancelling deletes the row rather than
                  // leaving a refusal behind (R-FRIEND-05), so it costs
                  // nothing to do again.
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    disabled={pending === entry.userId}
                    onClick={() => void remove(entry.userId)}
                  >
                    Cancel
                  </button>
                )}
              />
              <FriendsSection
                title="Friends"
                count={surface.friends.length}
                entries={surface.friends}
                testId="friends-accepted"
                renderActions={(entry) => (
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    disabled={pending === entry.userId}
                    onClick={() => setConfirming({ kind: "unfriend", entry })}
                  >
                    Remove
                  </button>
                )}
              />
            </>
          )}
        </div>
      </div>

      {/* Both of these are asked about because both are hard to undo, and for
          different reasons. A decline is kept, so the person who was refused
          can never ask again - the only way back is asking them yourself.
          Unfriending also revokes a way into your games (R-BLOCK-05's
          reasoning, without the block), and re-making it needs both people. */}
      {confirming?.kind === "decline" && (
        <ConfirmationDialog
          title="Decline this request?"
          description={`${confirming.entry.displayName} will not be able to ask again. You can still send them a request yourself later.`}
          confirmLabel="Decline"
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const userId = confirming.entry.userId;
            setConfirming(null);
            void remove(userId);
          }}
        />
      )}
      {confirming?.kind === "unfriend" && (
        <ConfirmationDialog
          title={`Remove ${confirming.entry.displayName}?`}
          description="You will both stop being able to join each other's games without an invitation. Either of you can ask again."
          confirmLabel="Remove"
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const userId = confirming.entry.userId;
            setConfirming(null);
            void remove(userId);
          }}
        />
      )}
    </div>
  );
}

/** One group, drawn only when it has something in it.

An empty heading is noise on a screen whose whole job is "what is waiting":
somebody with three friends and no requests should see *Friends*, not a
*Requests* heading with nothing under it. */
function FriendsSection({
  title,
  count,
  entries,
  testId,
  renderActions,
}: {
  title: string;
  count: number;
  entries: FriendEntry[];
  testId: string;
  renderActions: (entry: FriendEntry) => ReactNode;
}) {
  if (entries.length === 0) return null;
  return (
    <section className="friends-section">
      <h4 className="friends-section-heading">
        {title} <span className="friends-section-count">{count}</span>
      </h4>
      <ul className="friends-list" data-testid={testId}>
        {entries.map((entry) => (
          <li key={entry.userId} className="friends-row">
            <Avatar
              name={entry.displayName}
              nameColor={entry.nameColor ?? undefined}
              avatarUrl={entry.avatarUrl}
              isAnonymous={entry.isAnonymous}
              size={32}
            />
            <span
              className="friends-row-name"
              style={entry.nameColor ? { color: entry.nameColor } : undefined}
            >
              {entry.displayName}
            </span>
            <span className="friends-row-actions">{renderActions(entry)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
