import { useClock } from "../hooks/useClock";
import { useEffect, useState } from "react";

import { apiRequest } from "../lib/api";
import { fetchSuspensionDrawing, reportedDrawing } from "../lib/moderation";
import { socket } from "../lib/socket";
import { ReportedDrawing } from "./ReportedDrawing";
import {
  onSuspended,
  reportedMessages,
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
  const { timeFormat, dateTime } = useClock();
  const [suspension, setSuspension] = useState<Suspension | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => onSuspended(setSuspension), []);

  useEffect(() => {
    // The socket says it first for anyone mid-game; the refusal on their next
    // request says the same thing to everybody else.
    function onAccountSuspended(payload: unknown) {
      const body = (payload ?? {}) as Record<string, unknown>;
      reportSuspended({
        reason: typeof body.reason === "string" ? body.reason : null,
        expiresAt: typeof body.expiresAt === "string" ? body.expiresAt : null,
        messages: reportedMessages(body.messages),
        drawing: reportedDrawing(body.drawing),
      });
    }
    socket.on("account_suspended", onAccountSuspended);
    return () => {
      socket.off("account_suspended", onAccountSuspended);
    };
  }, []);

  if (!suspension) return null;

  async function signOut() {
    if (busy) return;
    setBusy(true);
    // Actually sign out. Navigating alone left the cookie in place, so the
    // next page load was refused again and the notice returned for ever - the
    // button promised an exit and moved nobody. Logout is one of the few paths
    // a suspended account may still reach, precisely so this can work.
    try {
      await apiRequest("/api/auth/logout", { method: "POST" });
    } catch {
      // A failed logout must not strand them on a dead button; the reload
      // below is what actually gets them off this screen either way.
    }
    // Hard reload rather than a route change: every store in memory belongs to
    // the account that just went away.
    window.location.href = "/";
  }

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
        <p className="modal-body">{suspensionDuration(suspension, new Date(), timeFormat)}</p>
        {suspension.messages.length > 0 && (
          <>
            <p className="modal-body suspension-evidence-label">
              {suspension.messages.length === 1
                ? "The message this was about:"
                : "The messages this was about:"}
            </p>
            {/* Their own words, as they were when the report was made. Scrolls
                inside the card rather than growing it off the screen. */}
            <ul className="suspension-evidence">
              {suspension.messages.map((message, index) => (
                <li key={`${message.at ?? index}-${index}`}>
                  {message.at && (
                    <span className="suspension-evidence-time">
                      {dateTime(new Date(message.at))}
                    </span>
                  )}
                  <span className="suspension-evidence-text">{message.text}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {suspension.drawing && (
          <>
            <p className="modal-body suspension-evidence-label">
              The drawing this was about:
            </p>
            {/* Their own work, as it was when the report was made. The bytes
                come through the one path a suspended account may still
                reach for them. */}
            <ReportedDrawing
              className="suspension-drawing"
              load={fetchSuspensionDrawing}
              label={`Your drawing of ${suspension.drawing.prompt}, as it was reported`}
              caption={<>You were asked to draw <strong>{suspension.drawing.prompt}</strong>.</>}
            />
          </>
        )}
        <button
          type="button"
          className="modal-button"
          disabled={busy}
          onClick={() => void signOut()}
        >
          {busy ? "Signing out…" : "Sign out"}
        </button>
      </div>
    </div>
  );
}
