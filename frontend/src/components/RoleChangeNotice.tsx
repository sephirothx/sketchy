import { useEffect, useState } from "react";

import { roleNoticeFromPayload, roleNoticeText } from "../lib/operatorAccess";
import {
  acknowledgeRoleNotice,
  fetchPendingRoleNotice,
  noticeAfterAcknowledgement,
  type PendingRoleNotice,
} from "../lib/roleNotices";
import { socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";

/** Tell a player that their own role changed, once.

An administrator grants or removes the moderator role from a page the player
never sees, and until now the only evidence was a **Moderation** entry that
appeared - or vanished - from their menu on some later load. This is the
sentence saying what happened.

Two routes, one payload: the socket reaches whoever is connected the moment the
change lands, wherever they are, and `GET /api/role-notices/pending` reaches
everybody else on their next visit. Acknowledging records that the notice
actually arrived, and settles anything older with it.

What it never carries is the reason the administrator recorded. That is ledger
text written for other administrators and can name a report or a second
account; what the player needs is what changed and what it means for them. */
export function RoleChangeNotice() {
  const userId = useAuthStore((state) => state.user?.id);
  const isGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [notice, setNotice] = useState<PendingRoleNotice | null>(null);
  const [busy, setBusy] = useState(false);
  // Whether this notice arrived *as the change happened*, over the socket. A
  // role change revokes every session the account holds (R-AUTH-20), so that
  // is also the moment this browser stopped being signed in: it cannot
  // acknowledge anything, and the honest thing to offer is the way back in.
  // The notice stays pending server-side and is acknowledged on the next
  // visit, by the fetch below, where the session is real again.
  const [signedOutByTheChange, setSignedOutByTheChange] = useState(false);

  useEffect(() => {
    // A guest cannot hold a role, so there can be no notice waiting for one -
    // and most visitors are guests, so asking anyway would put a request on
    // every page load to be told "nothing" every time.
    if (!hasResolved || !userId || isGuest) return;
    let cancelled = false;
    void fetchPendingRoleNotice()
      .then((result) => {
        if (cancelled) return;
        // Arrived on a later visit, so this session is fine and the button
        // does what it always did.
        setSignedOutByTheChange(false);
        setNotice(result.notice);
      })
      .catch(() => {
        // Nothing to do: the notice stays pending server-side and is fetched
        // again on the next visit.
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, isGuest, userId]);

  useEffect(() => {
    // A player who is online when the administrator acts hears it now; the
    // fetch above is the catch-up route for everybody else.
    function onRoleChanged(payload: unknown) {
      const pushed = roleNoticeFromPayload(payload);
      if (!pushed) return;
      setSignedOutByTheChange(true);
      setNotice(pushed);
      // Deliberately no `applyRole` here any more. It existed to make the menu
      // match the new role without a reload, and there is no longer a
      // signed-in menu to correct: this browser's session went with the role
      // change, and the next thing it does is sign in again.
    }
    socket.on("role_changed", onRoleChanged);
    return () => {
      socket.off("role_changed", onRoleChanged);
    };
  }, []);

  if (!notice) return null;
  const { title, body } = roleNoticeText(notice.role);

  async function dismiss() {
    if (busy || !notice) return;
    if (signedOutByTheChange) {
      // Nothing to acknowledge with: the credential this browser holds was
      // revoked by the change this notice is about. Clearing it locally is
      // what makes the sign-in form reachable, and the notice will be waiting
      // - still unacknowledged - when they are back.
      setNotice(null);
      await useAuthStore.getState().logout();
      return;
    }
    const settling = notice.id;
    setBusy(true);
    try {
      await acknowledgeRoleNotice(settling);
      // Only the notice that was acknowledged. A second change can land on the
      // socket while this request is in flight, and closing over "whatever is
      // showing" would take that newer one down unread.
      setNotice((current) => noticeAfterAcknowledgement(current, settling));
    } catch {
      // Leave the notice up: closing it without the receipt landing would
      // bring it back on the next visit, and the button can simply be pressed
      // again.
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay suspension-overlay">
      {/* `dialog` rather than `alertdialog`: a suspension or a warning is an
          urgent interruption a player has to read, and this is news. */}
      <div
        className="modal-card suspension-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="role-notice-title"
      >
        <h3 className="modal-title" id="role-notice-title">
          {title}
        </h3>
        <p className="modal-body">{body}</p>
        {signedOutByTheChange && (
          <p className="modal-body">
            You have been signed out on every device so the change can take
            effect. Sign in again to carry on.
          </p>
        )}
        <button
          type="button"
          className="modal-button"
          disabled={busy}
          onClick={() => void dismiss()}
        >
          {busy
            ? "One moment…"
            : signedOutByTheChange
              ? "Sign in again"
              : "Understood"}
        </button>
      </div>
    </div>
  );
}
