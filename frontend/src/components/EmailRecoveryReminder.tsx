import { XIcon } from "./icons";
import { useState } from "react";

import { AddEmailDialog } from "./AddEmailDialog";
import {
  acknowledgeReminder,
  maskEmail,
  shouldShowRecoveryReminder,
} from "../lib/accountRecovery";
import { useAuthStore } from "../store/authStore";
import { useEmailStateStore } from "../store/emailStateStore";
import { useGameStore } from "../store/gameStore";
import { ui } from "../content/ui/index.ts";

/** A standing note that this account cannot currently be recovered.

Email is optional, so somebody can register without one and never think about
it again - until they forget their password, when there is nothing anyone can
do for them. This is the reminder, deliberately shaped as a note rather than a
gate: it can be closed, and it comes back in a week rather than on every load.
It first appears a week after signing up, not on the page after the form that
called the address optional - the server decides that (R-AUTH-15).
The interval is kept on the account rather than in the browser, so it does not
restart on each new device or vanish when storage is cleared.

The state is the shared store's, not a copy read on mount: the address is
usually confirmed somewhere else - a tab opened from the email, or Settings -
and a copy kept here went on asking for a confirmation that had already
happened until the page was reloaded. */
export function EmailRecoveryReminder() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  // Silent in a room. This is a standing note about account hygiene, and a
  // note that can wait has no business landing on top of the drawing tools
  // while somebody is playing - which is exactly what it did, because the room
  // lays itself out to the viewport rather than flowing under a banner.
  const inRoom = useGameStore((state) => state.roomId !== null);
  const state = useEmailStateStore((store) => store.state);
  const refresh = useEmailStateStore((store) => store.refresh);
  const [dismissed, setDismissed] = useState(false);
  const [adding, setAdding] = useState(false);

  const registered = hasResolved && user !== null && !user.isAnonymous;

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
            /* Masked (R-SET-08): this banner sits across every screen. */
            ? ui.emailRecoveryReminder.confirmPendingAddressToFinishSetting({ pendingAddress: maskEmail(state.pendingAddress) })
            : ui.emailRecoveryReminder.thisAccountHasNoEmail}
        </span>
        {!state.pendingAddress && (
          <button type="button" onClick={() => setAdding(true)}>
            {ui.emailRecoveryReminder.addEmail}
          </button>
        )}
        <button
          type="button"
          className="email-reminder-dismiss"
          aria-label={ui.emailRecoveryReminder.dismiss}
          onClick={() => void close()}
        >
          <XIcon size={14} />
        </button>
      </div>
      {adding && (
        <AddEmailDialog
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            void refresh();
          }}
        />
      )}
    </>
  );
}
