import { useEffect, useState } from "react";

import {
  acknowledgeWarning,
  fetchPendingWarning,
  type PendingWarning,
} from "../lib/moderation";
import { socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";

/** Keep only a payload shaped like a warning; a malformed one is dropped
rather than rendered as "undefined" in front of the player. */
function warningFromPayload(payload: unknown): PendingWarning | null {
  if (!payload || typeof payload !== "object") return null;
  const body = (payload as { warning?: unknown }).warning;
  if (!body || typeof body !== "object") return null;
  const warning = body as Record<string, unknown>;
  if (typeof warning.id !== "string" || typeof warning.reason !== "string") {
    return null;
  }
  return {
    id: warning.id,
    reason: warning.reason,
    createdAt: typeof warning.createdAt === "string" ? warning.createdAt : "",
    messages: Array.isArray(warning.messages)
      ? warning.messages.filter(
          (line): line is { text: string; at: string | null } =>
            !!line && typeof (line as { text?: unknown }).text === "string",
        )
      : [],
  };
}

/** Show a moderator's warning to its player, once.

The step between a report going nowhere and an account being suspended:
nothing is restricted, but the player is told what was reported - in their own
words - and that a moderator looked. Acknowledging it records that the message
actually landed, and it does not come back. */
export function WarningNotice() {
  const userId = useAuthStore((state) => state.user?.id);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [warning, setWarning] = useState<PendingWarning | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!hasResolved || !userId) return;
    let cancelled = false;
    void fetchPendingWarning()
      .then((result) => {
        if (!cancelled) setWarning(result.warning);
      })
      .catch(() => {
        // Nothing to do: the warning stays pending server-side and will be
        // fetched again on the next visit.
      });
    return () => {
      cancelled = true;
    };
  }, [hasResolved, userId]);

  useEffect(() => {
    // A player who is online when the moderator decides hears it now; the
    // fetch above is the catch-up route for everybody else.
    function onModeratorWarning(payload: unknown) {
      const pushed = warningFromPayload(payload);
      if (pushed) setWarning(pushed);
    }
    socket.on("moderator_warning", onModeratorWarning);
    return () => {
      socket.off("moderator_warning", onModeratorWarning);
    };
  }, []);

  if (!warning) return null;

  async function dismiss() {
    if (busy || !warning) return;
    setBusy(true);
    try {
      await acknowledgeWarning(warning.id);
      setWarning(null);
    } catch {
      // Leave the notice up: closing it without the receipt landing would
      // mark nothing, and the player can simply press the button again.
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay suspension-overlay">
      <div
        className="modal-card suspension-card"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="warning-title"
      >
        <h3 className="modal-title" id="warning-title">
          A moderator warning
        </h3>
        <p className="modal-body suspension-reason">{warning.reason}</p>
        <p className="modal-body">
          Nothing on your account is restricted. A report about your behaviour
          was reviewed, and this is the outcome.
        </p>
        {warning.messages.length > 0 && (
          <>
            <p className="modal-body suspension-evidence-label">
              {warning.messages.length === 1
                ? "The message this was about:"
                : "The messages this was about:"}
            </p>
            {/* Reuses the suspension notice's evidence styling: both lists
                are "your own words, as reported". */}
            <ul className="suspension-evidence">
              {warning.messages.map((message, index) => (
                <li key={`${message.at ?? index}-${index}`}>
                  {message.at && (
                    <span className="suspension-evidence-time">
                      {new Date(message.at).toLocaleString()}
                    </span>
                  )}
                  <span className="suspension-evidence-text">{message.text}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        <button
          type="button"
          className="modal-button"
          disabled={busy}
          onClick={() => void dismiss()}
        >
          {busy ? "One moment…" : "Understood"}
        </button>
      </div>
    </div>
  );
}
