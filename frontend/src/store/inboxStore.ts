import { create } from "zustand";

import {
  EMPTY_INBOX,
  fetchInbox,
  markInboxRead,
  refreshedPage,
  withMore,
  type InboxPage,
} from "../lib/inbox";
import { pendingRoleFromPayload } from "../lib/operatorAccess";
import { useAuthStore } from "./authStore";

/**
 * The account's inbox as this tab last read it (#1436).
 *
 * Read again on every `inbox_changed`, on every (re)connection and whenever
 * the account changes, so the bell's count in every tab agrees with the
 * server: reading an entry anywhere moves it everywhere (R-INBOX-03). Held per
 * account - `owner` - so a sign-out or a switch never shows one account's
 * inbox to another, even for the moment a read is in flight.
 */
interface InboxStore extends InboxPage {
  owner: string | null;
  loaded: boolean;
  loadingMore: boolean;
  refresh: (owner: string) => Promise<void>;
  loadMore: () => Promise<void>;
  markRead: (ids: string[]) => Promise<void>;
  markAllRead: () => Promise<void>;
  clear: () => void;
}

// Reads in flight may land out of order; an older answer never replaces a
// newer one. A mark counts as a read too: it is issued like one, so a read
// sent before it cannot land after it and put the row back to unread.
let issued = 0;
let applied = 0;

export const useInboxStore = create<InboxStore>((set, get) => ({
  ...EMPTY_INBOX,
  owner: null,
  loaded: false,
  loadingMore: false,

  refresh: async (owner) => {
    const mine = ++issued;
    if (get().owner !== owner) set({ ...EMPTY_INBOX, owner, loaded: false });
    try {
      const page = await fetchInbox();
      if (mine < applied || get().owner !== owner) return;
      applied = mine;
      set((state) => ({ ...page, ...refreshedPage(page, state.entries, state.next), loaded: true }));
      // The offer rides the same read, so the account menu's way into
      // enrolment comes and goes with it.
      useAuthStore.getState().applyPendingRole(pendingRoleFromPayload(page));
    } catch {
      // Left as it was; the next push, connection or visit reads again.
    }
  },

  loadMore: async () => {
    const { next, owner, loadingMore } = get();
    if (!next || !owner || loadingMore) return;
    set({ loadingMore: true });
    try {
      const page = await fetchInbox(next);
      if (get().owner !== owner) return;
      set((state) => ({ entries: withMore(state.entries, page.entries), next: page.next }));
    } catch {
      // The button stays; pressing it again is the retry.
    } finally {
      set({ loadingMore: false });
    }
  },

  markRead: async (ids) => {
    const unread = new Set(get().entries.filter((e) => !e.read && ids.includes(e.id)).map((e) => e.id));
    if (unread.size === 0) return;
    const owner = get().owner;
    const mine = ++issued;
    applied = mine;
    set((state) => ({
      entries: state.entries.map((e) => (unread.has(e.id) ? { ...e, read: true } : e)),
      unreadCount: Math.max(0, state.unreadCount - unread.size),
    }));
    try {
      const left = await markInboxRead({ ids: [...unread] });
      // Only while nothing newer has been read since: a push read after this
      // mark already counts it, and more besides.
      if (get().owner === owner && applied === mine) set({ unreadCount: left });
    } catch {
      if (owner && get().owner === owner) void get().refresh(owner);
    }
  },

  markAllRead: async () => {
    const owner = get().owner;
    applied = ++issued;
    set((state) => ({ entries: state.entries.map((e) => ({ ...e, read: true })), unreadCount: 0 }));
    try {
      await markInboxRead({ all: true });
    } catch {
      if (owner && get().owner === owner) void get().refresh(owner);
    }
  },

  clear: () => set({ ...EMPTY_INBOX, owner: null, loaded: false }),
}));
