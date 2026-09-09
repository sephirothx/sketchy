import { create } from "zustand";

import {
  NO_FRIENDS,
  NO_FRIEND_CHANGES,
  friendListChanges,
  isNoFriendListRefusal,
  type FriendLists,
  type FriendListChanges,
} from "../lib/friends";
import {
  acceptFriend,
  listFriends,
  removeFriend,
  requestFriend,
} from "../lib/friendsApi";

interface FriendsStore {
  lists: FriendLists;
  /** Whether `lists` is an answer about `ownerId`, rather than a starting value.

  Read before acting on the lists, never inferred from them being empty: an
  account with no friends and an account whose lists have not arrived are the
  same shape, and only one of them may be offered a control. */
  loaded: boolean;
  /** Whose lists these are, so a second account never inherits the first's.

  The diff that decides what to announce is meaningless across a change of
  identity: signing in turns "no friends" into "four friends and two waiting
  requests", and every one of those would be announced as having just
  arrived. So an identity change clears the baseline instead of diffing
  against somebody else's. */
  ownerId: string | null;
  /** The account currently being acted on, so one row can show it is busy. */
  pending: string | null;
  /** What moved on the last read, and a counter that says it is new.

  A counter rather than a flag somebody has to clear: two requests arriving in
  a row produce the same shape twice, and a consumer comparing the object
  would show the first and miss the second. */
  notices: FriendListChanges & { seq: number };
  /** Re-read the lists for *accountId*, or for whoever they already belong to.

  The account is passed in rather than read from the auth store, so this
  module keeps its one job and the caller that knows the identity changed is
  the one that says so. */
  refresh: (accountId?: string | null) => Promise<void>;
  add: (userId: string) => Promise<void>;
  accept: (userId: string) => Promise<void>;
  remove: (userId: string) => Promise<void>;
  reset: () => void;
}

/** Every mutation refetches rather than patching locally.

The server decides what a request became — a new pending row, an acceptance of
one that was already waiting, or deliberately nothing at all — and it answers
the last two identically on purpose. A local patch would have to guess, and
would guess wrong exactly where the guess matters. The lists are small and the
call is a button press.

Through `refresh` rather than reading the lists here, so this read is ordered
and owned like every other one. It used to call `listFriends` directly, which
meant a mutation begun before signing out could land its answer on the next
account's lists, and could overwrite a newer refresh because nothing recorded
it. `pending` is cleared only if this is still the same person acting, for the
same reason. */
async function afterMutating(
  get: () => FriendsStore,
  set: (partial: Partial<FriendsStore>) => void,
  owner: string | null,
) {
  try {
    await get().refresh();
  } finally {
    if (get().ownerId === owner) set({ pending: null });
  }
}

/** Run one mutation, then re-read — refusing if somebody else is mid-action.

The owner is captured before the call so the refetch and the busy flag both
belong to the identity that started it. */
async function mutate(
  get: () => FriendsStore,
  set: (partial: Partial<FriendsStore>) => void,
  userId: string,
  call: (userId: string) => Promise<unknown>,
) {
  if (get().pending) return;
  const owner = get().ownerId;
  set({ pending: userId });
  try {
    await call(userId);
  } catch {
    // The refetch below is what corrects the row either way — including when
    // the server refused, which it does for reasons it will not name.
  }
  await afterMutating(get, set, owner);
}

/** Replace the lists, and say what moved.

The diff runs on every read rather than only on the socket event, because a
mutation refetches too and somebody else's request may have landed in between.
It is skipped before the first read has landed: everything is new then, and a
fresh tab is not the moment to announce a week of requests. */
function absorb(
  set: (partial: Partial<FriendsStore>) => void,
  get: () => FriendsStore,
  next: FriendLists,
) {
  const previous = get();
  if (!previous.loaded) {
    set({ lists: next, loaded: true });
    return;
  }
  const changes = friendListChanges(previous.lists, next);
  if (changes.arrived.length === 0 && changes.accepted.length === 0) {
    set({ lists: next });
    return;
  }
  set({
    lists: next,
    notices: { ...changes, seq: previous.notices.seq + 1 },
  });
}

/** Ordering for reads in flight, so a slow one cannot land on a newer answer.

Refreshes are triggered by four unrelated things — the account changing, a
mutation, a `friends_changed` event and a reconnect — so two being in flight
at once is ordinary rather than exceptional, and the network decides which
returns first.

The rule is **apply the first answer that arrives, and never an older one
after a newer one** — not "only the newest issued may write". The difference
matters because the first answer for an identity is what establishes the
baseline the notices diff against: dropping it because a newer read is
already in flight makes *that* read the baseline instead, and whatever
changed in between is absorbed into it silently. That is a friend request
being accepted and nobody being told. */
let readSeq = 0;
let appliedSeq = 0;

export const useFriendsStore = create<FriendsStore>((set, get) => ({
  lists: NO_FRIENDS,
  loaded: false,
  ownerId: null,
  pending: null,
  notices: { ...NO_FRIEND_CHANGES, seq: 0 },
  refresh: async (accountId) => {
    // `undefined` means "whoever these already belong to" — the mutation, the
    // socket event and the reconnect all mean that. `null` is a real value:
    // signed out, or a guest.
    const owner = accountId === undefined ? get().ownerId : accountId;
    if (owner !== get().ownerId) {
      // A different person is reading. Their first answer is a baseline, not
      // a change, so nothing of the previous identity's survives to diff it.
      set({ ownerId: owner, lists: NO_FRIENDS, loaded: false });
    }
    const seq = ++readSeq;
    // Superseded by an answer that was issued later and already landed, or
    // addressed to somebody who is no longer the one reading.
    const overtaken = () => seq <= appliedSeq || get().ownerId !== owner;
    try {
      const lists = await listFriends();
      if (overtaken()) return;
      appliedSeq = seq;
      absorb(set, get, lists);
    } catch (error) {
      if (overtaken()) return;
      appliedSeq = seq;
      // A guest is refused, and that refusal *is* their answer: they have no
      // friends list, and every control that would use one is hidden anyway.
      //
      // Nothing else is. A timeout, a dropped connection or a 500 says
      // nothing about who this account is friends with, and treating it as
      // "no friends, and we know it" is worse than saying nothing: the lists
      // empty on screen, the profile starts deriving `Add friend` from a
      // state that is not true — and pressing that accepts a request it
      // should have shown — and the next successful read diffs against the
      // false empty list and announces every existing request as new. So a
      // failure keeps the last good answer, and an unanswered first read
      // stays unanswered.
      if (isNoFriendListRefusal(error)) {
        set({ lists: NO_FRIENDS, loaded: true });
      }
    }
  },
  add: (userId) => mutate(get, set, userId, requestFriend),
  accept: (userId) => mutate(get, set, userId, acceptFriend),
  remove: (userId) => mutate(get, set, userId, removeFriend),
  // The notice counter is not reset: it only ever has to keep moving for a
  // consumer to notice, and restarting it at zero after a read that was
  // already at zero would hide the next change. Bumping `readSeq` is what
  // stops a read that is already in flight from landing afterwards.
  reset: () => {
    // Everything in flight is now older than the reset, so none of it lands.
    readSeq += 1;
    appliedSeq = readSeq;
    set({ lists: NO_FRIENDS, loaded: false, ownerId: null, pending: null });
  },
}));
