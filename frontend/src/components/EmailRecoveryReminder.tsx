import { useCallback, useEffect, useState } from "react";

import { AddEmailDialog } from "./AddEmailDialog";
import {
  acknowledgeReminder,
  readEmailState,
  shouldShowRecoveryReminder,
  type EmailState,
} from "../lib/accountRecovery";
import { useAuthStore } from "../store/authStore";
import { useGameStore } from "../store/gameStore";

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
  // Silent in a room. This is a standing note about account hygiene, and a
  // note that can wait has no business landing on top of the drawing tools
  // while somebody is playing - which is exactly what it did, because the room
  // lays itself out to the viewport rather than flowing under a banner.
  const inRoom = useGameStore((state) => state.roomId !== null);
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
  // The null check is repeated for the compiler's benefit - the rule already
  // covers it, but it cannot narrow `state` for the markup below.
  if (!state || !shouldShowRecoveryReminder({ registered, inRoom, dismissed, state })) {
    return null;
  }

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
