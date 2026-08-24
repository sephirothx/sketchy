import { useEffect, useState } from "react";

import { socket } from "../lib/socket";
import {
  onSuspended,
  reportSuspended,
  suspensionDuration,
  type Suspension,
} from "../lib/suspension";

/** Tell a suspended player what happened, before they are simply signed out.

Suspending revokes every session and ends every live seat at once, so without
this the experience is a game that stops and a page that starts refusing
things. The notice cannot be dismissed - there is nothing behind it to go back
to - and signing out is the only way on, which is where they were headed
anyway. */
export function SuspensionNotice() {
  const [suspension, setSuspension] = useState<Suspension | null>(null);

  useEffect(() => onSuspended(setSuspension), []);

  useEffect(() => {
    // The socket says it first for anyone mid-game; the refusal on their next
    // request says the same thing to everybody else.
    function onAccountSuspended(payload: unknown) {
      const body = (payload ?? {}) as Record<string, unknown>;
      reportSuspended({
        reason: typeof body.reason === "string" ? body.reason : null,
        expiresAt: typeof body.expiresAt === "string" ? body.expiresAt : null,
      });
    }
    socket.on("account_suspended", onAccountSuspended);
    return () => {
      socket.off("account_suspended", onAccountSuspended);
    };
  }, []);

  if (!suspension) return null;

  return (
    <div className="modal-overlay suspension-overlay">
      <div
        className="modal-card suspension-card"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="suspension-title"
      >
        <h3 className="modal-title" id="suspension-title">
          Your account is suspended
        </h3>
        {suspension.reason && (
          <p className="modal-body suspension-reason">{suspension.reason}</p>
        )}
        <p className="modal-body">{suspensionDuration(suspension)}</p>
        <button
          type="button"
          className="modal-button"
          onClick={() => {
            // Everything is already revoked server-side; this clears what the
            // browser is still holding and starts them somewhere coherent.
            window.location.href = "/";
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
