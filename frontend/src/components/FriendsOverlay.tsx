import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import {
  addableRecentPlayers,
  friendsSurface,
  friendsSurfaceIsEmpty,
  type FriendEntry,
  type RecentPlayer,
} from "../lib/friends";
import { listRecentPlayers } from "../lib/friendsApi";
import { FriendButton } from "./FriendButton";
import { useCloseOverlay } from "../hooks/useOverlayRoute";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { useAuthStore } from "../store/authStore";
import { useFriendsStore } from "../store/friendsStore";
import { Avatar } from "./ui/Avatar";
import { Button } from "./ui/Button";
import { ConfirmationDialog } from "./ConfirmationDialog";
import { UsersIcon, XIcon } from "./icons";
import { ui } from "../content/ui/index.ts";

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
  const [recent, setRecent] = useState<RecentPlayer[]>([]);

  // Opened from a menu that may have been sitting there a while, and the lists
  // move without this screen being on. Cheap, and the alternative is a stale
  // Accept button for a request that has already been withdrawn.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Fetched here rather than app-wide: it costs a join over game history, and
  // nothing outside this screen reads it. A guest is refused, which is the
  // ordinary case rather than a fault - they simply get no suggestions.
  useEffect(() => {
    if (isGuest) return;
    let cancelled = false;
    void (async () => {
      try {
        const found = await listRecentPlayers();
        if (!cancelled) setRecent(found);
      } catch {
        // A suggestion list is the one thing here that may simply not
        // arrive: everything else on the screen is still true without it.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isGuest]);

  useFocusTrap(dialogRef, { onEscape: close, initialFocusRef: closeButtonRef });

  const surface = useMemo(() => friendsSurface(lists), [lists]);
  // Filtered against the lists rather than by the server: an account missing
  // from the endpoint's answer would be readable, and "missing because they
  // declined you" is the fact R-FRIEND-04 refuses to disclose. So the server
  // returns everyone and the client drops only what it can already see.
  const suggestions = useMemo(
    () => addableRecentPlayers(recent, lists),
    [recent, lists],
  );

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
            <span>{ui.friendsOverlay.friends}</span>
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            className="close-icon-button"
            onClick={close}
            title={ui.friendsOverlay.close}
            aria-label={ui.friendsOverlay.closeFriends}
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
              {ui.friendsOverlay.friendsNeedAccountGuestNameBelongs}
            </p>
          ) : !loaded ? (
            <p className="friends-empty">{ui.friendsOverlay.loading}</p>
          ) : friendsSurfaceIsEmpty(surface) && suggestions.length === 0 ? (
            <p className="friends-empty">
              {ui.friendsOverlay.noFriendsYetAddSomebodyFrom}
            </p>
          ) : (
            <>
              <FriendsSection
                title={ui.friendsOverlay.requests}
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
                      {ui.friendsOverlay.accept}
                    </Button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-compact"
                      disabled={pending === entry.userId}
                      onClick={() => setConfirming({ kind: "decline", entry })}
                    >
                      {ui.friendsOverlay.decline}
                    </button>
                  </>
                )}
              />
              <FriendsSection
                title={ui.friendsOverlay.sent}
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
                    {ui.friendsOverlay.cancel}
                  </button>
                )}
              />
              <FriendsSection
                title={ui.friendsOverlay.friends}
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
                    {ui.friendsOverlay.remove}
                  </button>
                )}
              />
              <RecentPlayersSection players={suggestions} />
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
          title={ui.friendsOverlay.declineThisRequest}
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
          title={ui.friendsOverlay.removeConfirm({ name: confirming.entry.displayName })}
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


/** People the viewer finished a game with lately, and has not asked yet.

The answer to "I played with them yesterday and now I cannot find them": the
lobby only ever knew who was standing in it, and this knows who somebody has
actually been playing with. Not a search and not a directory (N-06) - every
row here is somebody the viewer has already met, in a game they were both in.

Last, under the lists it suggests additions to, because it is an offer rather
than something waiting for an answer. */
function RecentPlayersSection({ players }: { players: RecentPlayer[] }) {
  if (players.length === 0) return null;
  return (
    <section className="friends-section">
      <h4 className="friends-section-heading">{ui.friendsOverlay.recentlyPlayedWith}</h4>
      <ul className="friends-list" data-testid="friends-recent">
        {players.map((player) => (
          <li key={player.userId} className="friends-row">
            <Avatar
              name={player.displayName}
              nameColor={player.nameColor ?? undefined}
              avatarUrl={player.avatarUrl}
              isAnonymous={false}
              size={32}
            />
            <span
              className="friends-row-name"
              style={player.nameColor ? { color: player.nameColor } : undefined}
            >
              {player.displayName}
            </span>
            <span className="friends-row-actions">
              <FriendButton
                action="add"
                userId={player.userId}
                displayName={player.displayName}
              />
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
