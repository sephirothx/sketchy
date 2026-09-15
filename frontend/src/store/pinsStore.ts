import { useEffect } from "react";
import { create } from "zustand";

import { fetchProfilePins, setMyPins } from "../lib/profile";
import { useAuthStore } from "./authStore";

/** What a mutation computes: the next whole shelf, or `null` to refuse without a request. */
export type ShelfMutation = (current: readonly string[]) => string[] | null;

interface PinsStore {
  /** Whose shelf `turnIds` describes, so a second account never inherits the first's. */
  ownerId: string | null;
  /** The signed-in player's pinned turn ids, in shelf order. */
  turnIds: string[];
  /** Whether `turnIds` is an answer about `ownerId` rather than a starting value.

  Read before offering a control, never inferred from the list: an empty
  shelf and a shelf not yet fetched are the same shape, and a whole-list
  write computed from the second would erase the first. */
  loaded: boolean;
  /** A write is in flight; every control waits on the same one. */
  pending: boolean;
  /** The last read for `ownerId` failed; `attempt` counts them, and the
      hook retries with a growing pause until `RETRY_DELAYS_MS` runs out. */
  failed: boolean;
  attempt: number;
  /** Read the shelf for `accountId`; `null` forgets it. */
  load: (accountId: string | null) => Promise<void>;
  /**
   * Change the shelf. Mutations are one queue: each computes its list from
   * the state as it stands when its turn comes, never from the state at the
   * press, so two controls pressed together cannot each send a list that
   * forgets the other's pin. Refused with `ShelfNotReadyError` until the
   * shelf for the signed-in account has been read - a whole-list write from
   * an unread shelf would erase it. Resolves `false` when the mutation
   * itself declined (`null`), `true` once the server has the new list.
   */
  mutate: (change: ShelfMutation) => Promise<boolean>;
  reset: () => void;
}

export class ShelfNotReadyError extends Error {
  constructor() {
    super("pinned drawings not loaded yet");
    this.name = "ShelfNotReadyError";
  }
}

// Module-level rather than store fields: the queue tail and the generation
// are bookkeeping for the actions, not state anything renders.
let queue: Promise<unknown> = Promise.resolve();
let generation = 0;

/** Pauses before each retry of a failed read; after the last, the shelf
    stays unread until the identity changes or the page is reloaded. */
export const RETRY_DELAYS_MS = [2_000, 5_000, 10_000, 20_000] as const;
let inFlight: { accountId: string; token: object; promise: Promise<void> } | null = null;

export const usePinsStore = create<PinsStore>((set, get) => ({
  ownerId: null,
  turnIds: [],
  loaded: false,
  pending: false,
  failed: false,
  attempt: 0,
  load: (accountId) => {
    if (!accountId) {
      generation += 1;
      inFlight = null;
      set({ ownerId: null, turnIds: [], loaded: false, failed: false, attempt: 0 });
      return Promise.resolve();
    }
    // One read per account at a time: every row of a game table asks on
    // its first render, and they share the answer rather than each fetching.
    if (inFlight?.accountId === accountId) return inFlight.promise;
    const mine = ++generation;
    const token = {};
    // A retry for the same account keeps its attempt count; a new account
    // starts from none.
    const attempt = get().ownerId === accountId ? get().attempt : 0;
    set({ ownerId: accountId, turnIds: [], loaded: false, failed: false, attempt });
    const promise = (async () => {
      try {
        const shelf = await fetchProfilePins(accountId);
        // A mutation or a newer load since this was sent has fresher ids
        // than this answer; an old answer must not roll them back.
        if (mine !== generation) return;
        set({ turnIds: shelf.pins.map((pin) => pin.turnId), loaded: true, failed: false, attempt: 0 });
      } catch {
        if (mine !== generation) return;
        set({ turnIds: [], loaded: false, failed: true, attempt: attempt + 1 });
      } finally {
        if (inFlight?.token === token) inFlight = null;
      }
    })();
    inFlight = { accountId, token, promise };
    return promise;
  },
  mutate: (change) => {
    const run = async (): Promise<boolean> => {
      // Let a read for the signed-in account land first, so a press that
      // arrives before the shelf does waits for it instead of erasing it.
      if (inFlight) await inFlight.promise;
      const { loaded, ownerId, turnIds } = get();
      const account = useAuthStore.getState().user;
      if (!loaded || !ownerId || !account || account.id !== ownerId) {
        throw new ShelfNotReadyError();
      }
      const next = change(turnIds);
      if (next === null) return false;
      // The write is for this identity and this generation: an answer that
      // arrives after a sign-out, a sign-in or a newer read belongs to a
      // shelf nobody is looking at any more, and is dropped rather than
      // written over the account now signed in.
      const mine = ++generation;
      set({ pending: true });
      try {
        const answer = await setMyPins(next);
        if (mine !== generation || get().ownerId !== ownerId) return true;
        set({ turnIds: answer.pins.map((pin) => pin.turnId), loaded: true });
        return true;
      } finally {
        set({ pending: false });
      }
    };
    // Chained on the tail whether or not the previous one failed: a refused
    // write must not block the next press.
    const turn = queue.then(run, run);
    queue = turn.catch(() => undefined);
    return turn;
  },
  reset: () => {
    generation += 1;
    inFlight = null;
    set({ ownerId: null, turnIds: [], loaded: false, pending: false, failed: false, attempt: 0 });
  },
}));

/**
 * The store, kept in step with the signed-in account: loaded once per
 * registered account, forgotten when there is none. Guests hold no shelf and
 * are not asked for one. `ready` says the controls may be offered.
 */
export function useMyPins(): PinsStore & { ready: boolean } {
  const user = useAuthStore((s) => s.user);
  const accountId = user && !user.isAnonymous ? user.id : null;
  const store = usePinsStore();
  useEffect(() => {
    if (store.ownerId === accountId) return;
    void usePinsStore.getState().load(accountId);
  }, [accountId, store.ownerId]);
  // A failed read is retried with a growing pause, a bounded number of
  // times, so a blip in connectivity does not leave every Pin control
  // disabled until the page is reloaded - and a server that keeps refusing
  // is not asked for ever.
  useEffect(() => {
    if (!store.failed || !accountId || store.ownerId !== accountId) return;
    const delay = RETRY_DELAYS_MS[store.attempt - 1];
    if (delay === undefined) return;
    const timer = window.setTimeout(() => {
      void usePinsStore.getState().load(accountId);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [store.failed, store.attempt, store.ownerId, accountId]);
  return { ...store, ready: store.loaded && store.ownerId !== null && store.ownerId === accountId };
}
