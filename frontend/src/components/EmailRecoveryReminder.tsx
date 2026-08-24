import { useCallback, useEffect, useState } from "react";

import { AddEmailDialog } from "./AddEmailDialog";
import {
  acknowledgeReminder,
  readEmailState,
  type EmailState,
} from "../lib/accountRecovery";
import { useAuthStore } from "../store/authStore";

/** A standing note that this account cannot currently be recovered.

Email is optional, so somebody can register without one and never think about
it again - until they forget their password, when there is nothing anyone can
do for them. This is the reminder, deliberately shaped as a note rather than a
gate: it can be closed, and it comes back in a week rather than on every load.
The interval is kept on the account rather than in the browser, so it does not
restart on each new device or vanish when storage is cleared. */
export function EmailRecoveryReminder() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [state, setState] = useState<EmailState | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [adding, setAdding] = useState(false);

  const registered = hasResolved && user !== null && !user.isAnonymous;

  const refresh = useCallback(() => {
    if (!registered) return;
    void readEmailState()
      .then(setState)
      // A reminder that cannot be fetched is not worth an error: the player
      // came here to draw.
      .catch(() => setState(null));
  }, [registered]);

  useEffect(refresh, [refresh]);

  // Guests have nothing to recover yet - claiming the account is the step
  // being asked for there, not an address.
  if (!registered || !state?.reminderDue || dismissed) return null;

  async function close() {
    setDismissed(true);
    // Restarting the clock is the point; failing to is merely a repeat.
    await acknowledgeReminder().catch(() => undefined);
  }

  return (
    <>
      <div className="email-reminder-banner" role="status" aria-live="polite">
        <span>
          {state.pendingAddress
            ? `Confirm ${state.pendingAddress} to finish setting up account recovery.`
            : "This account has no email address, so a forgotten password cannot be reset."}
        </span>
        {!state.pendingAddress && (
          <button type="button" onClick={() => setAdding(true)}>
            Add an email
          </button>
        )}
        <button
          type="button"
          className="email-reminder-dismiss"
          aria-label="Dismiss"
          onClick={() => void close()}
        >
          ×
        </button>
      </div>
      {adding && (
        <AddEmailDialog
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            refresh();
          }}
        />
      )}
    </>
  );
}
