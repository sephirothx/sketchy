import { create } from "zustand";

import { readEmailState, type EmailState } from "../lib/accountRecovery.ts";

interface EmailStateStore {
  /** The account's recovery address state, or null before the first answer. */
  state: EmailState | null;
  /** Whose state this is, so a second account never inherits the first's. */
  ownerId: string | null;
  /** Re-read for *accountId*, or for whoever the state already belongs to.

  `undefined` means "the same account" - a save, the `email_state_changed`
  event and a reconnect all mean that. `null` is signed out or a guest, who
  have no address to recover through and are answered without asking. */
  refresh: (accountId?: string | null) => Promise<void>;
}

/** Ordering for reads in flight, so a slow one cannot land on a newer answer.

One store rather than a copy per component, because the three things showing
this state - the reminder banner, the Settings row, and the dialog - each used
to read it once and keep it. Confirming the address in one never reached the
others, and the banner went on asking for a confirmation that had happened.

The ordering is the other half of that bug. The confirmation page loads with
the banner on it, and the banner's read and the confirmation itself leave
together: when the read won, the page said "confirmed" under a banner saying
"confirm". The refresh the page makes afterwards is issued later, so an older
answer arriving after it is discarded rather than painted over it. */
let readSeq = 0;
let appliedSeq = 0;

export const useEmailStateStore = create<EmailStateStore>((set, get) => ({
  state: null,
  ownerId: null,
  refresh: async (accountId) => {
    const owner = accountId === undefined ? get().ownerId : accountId;
    if (owner !== get().ownerId) set({ ownerId: owner, state: null });
    const seq = ++readSeq;
    if (owner === null) {
      // Claiming the slot keeps a read still in flight for the previous
      // account from landing afterwards.
      appliedSeq = seq;
      set({ state: null });
      return;
    }
    const overtaken = () => seq <= appliedSeq || get().ownerId !== owner;
    try {
      const next = await readEmailState();
      if (overtaken()) return;
      appliedSeq = seq;
      set({ state: next });
    } catch {
      // A read that failed says nothing about the address, so the last good
      // answer stands. None of these surfaces is worth an error: the player
      // came here to draw.
    }
  },
}));
