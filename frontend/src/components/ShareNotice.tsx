import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { withdrawFromGallery } from "../lib/gallery";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import {
  acknowledgeShareNotices,
  fetchPendingShareNotices,
  laterOf,
  pendingShareNoticesFrom,
  type PendingShareNotices,
} from "../lib/shareNotices";
import { socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";
import { ModalShell } from "./ui/ModalShell";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";

/** Tell a drawer that somebody else shared their drawing to the Gallery (#1430).

Another player may share a public game's drawing without asking (R-SHARE-02),
so its drawer hears about it once, here, and can take it back out on the spot
(R-SHARE-09). Two routes, one payload, the role notice's arrangement: the
socket reaches a drawer who is connected when the share lands, and
`GET /api/share-notices/pending` reaches everybody else once per visit.

Held while a game is being played: a card over somebody's turn would be the
one thing worse than not being told. It waits for the waiting room, the lobby,
or any page outside a room. */
export function ShareNotice() {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const playing = useGameStore((state) => state.roomId !== null && state.roomState === "playing");
  const [pending, setPending] = useState<PendingShareNotices | null>(null);
  const [takenOut, setTakenOut] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const askedFor = useRef<string | null>(null);
  const primaryRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    // Guests too: a guest's drawing can be shared like anybody's. Once per
    // identity per visit, not per reconnect.
    if (!hasResolved || !userId || askedFor.current === userId) return;
    askedFor.current = userId;
    let cancelled = false;
    void fetchPendingShareNotices()
      .then((read) => {
        if (!cancelled) setPending((current) => laterOf(current, read));
      })
      .catch(() => {
        // Nothing to do: the notices stay pending and are read next visit.
        askedFor.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, userId]);

  useEffect(() => {
    function onPushed(payload: unknown) {
      const read = pendingShareNoticesFrom(payload);
      if (read) setPending((current) => laterOf(current, read));
    }
    socket.on("drawing_share_notice", onPushed);
    return () => {
      socket.off("drawing_share_notice", onPushed);
    };
  }, []);

  if (!pending || pending.notices.length === 0 || playing) return null;
  const shown = pending.notices;
  const more = Math.max(0, pending.total - shown.length);

  async function settle() {
    if (busy || !pending) return;
    const newest = pending.notices[0];
    setBusy(true);
    setFailed(false);
    try {
      await acknowledgeShareNotices(newest.id);
      // Only what was settled: a push that arrived meanwhile stays up.
      setPending((current) => (current && current.notices[0]?.id === newest.id ? null : current));
      setTakenOut(new Set());
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  async function takeOut(turnId: string) {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await withdrawFromGallery(turnId);
      setTakenOut((current) => new Set(current).add(turnId));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ModalShell
      title={ui.shareNotice.title({ count: pending.total })}
      testId="share-notice"
      initialFocusRef={primaryRef}
      onDismiss={() => void settle()}
      footer={
        <button
          ref={primaryRef}
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => void settle()}
        >
          {ui.shareNotice.ok}
        </button>
      }
    >
      <ul className="share-notice-list">
        {shown.map((notice) => (
          <li key={notice.id} className="share-notice-item" data-testid="share-notice-item">
            <p className="share-notice-line">
              {fill(ui.shareNotice.sharedYourDrawing, {
                sharer: (
                  <strong
                    className={playerNameClass(notice.sharerIsAnonymous)}
                    style={playerNameStyle(notice.sharerNameColor ?? undefined, notice.sharerIsAnonymous)}
                  >
                    {notice.sharerDisplayName}
                  </strong>
                ),
                prompt: <strong>{notice.prompt}</strong>,
              })}
            </p>
            <span className="share-notice-actions">
              {takenOut.has(notice.turnId) ? (
                <span className="share-notice-done">{ui.shareNotice.takenOut}</span>
              ) : (
                <>
                  <Link
                    className="btn btn-ghost btn-compact"
                    to={`/gallery/${encodeURIComponent(notice.turnId)}`}
                    onClick={() => void settle()}
                  >
                    {ui.shareNotice.view}
                  </Link>
                  <button
                    type="button"
                    className="btn btn-secondary btn-compact"
                    disabled={busy}
                    data-testid="share-notice-take-out"
                    onClick={() => void takeOut(notice.turnId)}
                  >
                    {ui.shareNotice.takeOut}
                  </button>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
      {more > 0 && <p className="modal-body share-notice-more">{ui.shareNotice.andMore({ count: more })}</p>}
      <p className="modal-body share-notice-hint">{ui.shareNotice.youCanAlways}</p>
      {failed && (
        <p className="auth-error" role="alert">
          {ui.dialog.couldNotSave}
        </p>
      )}
    </ModalShell>
  );
}
