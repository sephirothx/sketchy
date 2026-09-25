import { create } from "zustand";
import { apiRequest, onUnexpectedSignOut } from "../lib/api";
import { assertPasskey } from "../lib/passkeys";
import { emitTransient, reconnectWithCurrentIdentity, socket } from "../lib/socket";
import { historyPortFor, leaveRoomHistory } from "../lib/roomHistory";
import { useGameStore } from "./gameStore";
import { isPaletteColor, useSettingsStore } from "./settingsStore";
import { nicknameError } from "../lib/roomEntryState";
import {
  applyAccountSettings,
  currentSettingsPayload,
  fetchUserSettings,
  type AccountSettings,
} from "../lib/userSettings";
import { loadCatalogue, ui } from "../content/ui/index.ts";

export interface AuthUser {
  id: string;
  username: string | null;
  displayName: string;
  nameColor: string | null;
  /** The uploaded picture's URL (#573), or null for the initial. */
  avatarUrl: string | null;
  isAnonymous: boolean;
  /** Decides which staff entries the menu offers. Never the authorization -
      every endpoint behind them checks the role again for itself. */
  role: "user" | "moderator" | "admin";
  /** A staff role that has been offered and is waiting on this account to set
      up a second factor (R-AUTH-20). Not a role: it authorizes nothing, and
      it is the only reason an ordinary player is shown anything about
      two-factor authentication at all. */
  pendingRole: "moderator" | "admin" | null;
  createdAt: string | null;
  lastLoginAt: string | null;
  /** A guest whose name somebody online took while they were away, and who
      arrived first (R-ACCT-09). Only `GET /api/auth/me` says so, and a
      refusal with `name_in_use` sets it; choosing a new name clears it,
      because the account the server hands back carries no such flag. */
  nameInUse?: boolean;
}

/** Thrown when an action needs a name and the draft cannot supply one. */
export class IdentityRequiredError extends Error {}

interface AuthStore {
  user: AuthUser | null;
  isLoading: boolean;
  /** True once fetchMe has settled, successfully or not. */
  hasResolved: boolean;
  /**
   * The name typed into the first-run block but not yet submitted.
   *
   * Held here rather than inside that component because a visitor who types a
   * name and then presses Create or Join plainly means to play under it, and
   * making them press a second button first is a step that exists only
   * because the state was in the wrong place.
   */
  nameDraft: string;
  setNameDraft: (nameDraft: string) => void;
  /**
   * Make sure this visitor has an account, provisioning from the draft name.
   *
   * Returns the account, or throws with the message the field should show.
   */
  ensureIdentity: () => Promise<AuthUser>;
  fetchMe: () => Promise<AuthUser | null>;
  /**
   * Re-read the account and, if it is not the one this tab was, become it
   * the way a sign-in does: seat released, socket bounced (#1006). `fetchMe`
   * only writes the store, and the socket reads the cookie once at the
   * handshake - so a page that changed the account on the server (a
   * password reset completed as a guest) and then only re-read it entered
   * the next room as the guest it had been.
   */
  adoptFromServer: (options?: { rebindSocket?: boolean }) => Promise<AuthUser | null>;
  /**
   * Adopt an offer the account's own socket room just announced.
   *
   * What the account UI offers, and nothing else: `pendingRole` authorizes
   * nothing (R-ROLE-01), so this cannot open a door — it stops the app from
   * hiding the one thing the offer asks for. Without it, a player who set the
   * notice aside with "Later" would find no way to enrol until they reloaded,
   * because the entry appears only for an account with an offer and that
   * value was last read at startup.
   *
   * Deliberately not an identity change. `installIdentity` bumps
   * `identityVersion` and the callers around it bounce the socket, because the
   * account underneath has changed; here it is the same account with
   * something waiting on it, and bouncing would drop the player out of
   * whatever they are doing to learn something the socket already told them.
   */
  applyPendingRole: (pendingRole: AuthUser["pendingRole"]) => void;
  /** Record that the server refused this guest's name because somebody who
      arrived first is using it, so every place that asks for a name asks. */
  markNameInUse: () => void;
  setDisplayName: (displayName: string) => Promise<AuthUser>;
  setNameColor: (nameColor: string) => Promise<AuthUser>;
  register: (username: string, password: string, email?: string) => Promise<AuthUser>;
  /**
   * `code` is the second factor, sent only when the server has asked for one
   * (R-AUTH-20): a staff sign-in is refused once with a header saying a code
   * is wanted, and the form retries with it.
   */
  login: (username: string, password: string, code?: string) => Promise<AuthUser>;
  /**
   * Sign in with a passkey: one assertion, no username and no password
   * (R-AUTH-23). Everything after it is what a password sign-in does, because
   * it is the same transition.
   */
  signInWithPasskey: () => Promise<AuthUser>;
  logout: () => Promise<void>;
}

/**
 * The socket reads the session cookie once, at handshake time, so it cannot
 * notice that the cookie changed underneath it. Bouncing the transport makes
 * it handshake again as the new account; `useRoomSessionReconnect` then
 * reconnects to the current room on `connect`, which is what updates the player's
 * identity in-game without a page reload.
 */
function reconnectSocketAsNewIdentity(): void {
  if (socket.connected) socket.disconnect();
  socket.connect();
}

/**
 * Give up the current live seat before switching to a different account.
 *
 * Registering keeps the same user id, so that seat is simply upgraded in
 * place. Logging in does not: it moves to another account entirely, and the
 * server would find no seat for the new identity, seat the player a second
 * time, and leave the old one occupying a slot until it timed out. Leaving
 * first makes the handover explicit. Persisted guest history is linked to the
 * account by the server; the in-memory seat still has to leave cleanly.
 */
function releaseSeatBeforeIdentityChange(): void {
  // Read before the session is cleared, which is what forgets the seat.
  const { playerId, code } = useGameStore.getState();
  if (playerId && socket.connected) {
    emitTransient("leave_room");
  }
  useGameStore.getState().clearSession();
  // The seat's history entries go with it, as on any other way out (R-UX-15),
  // but nothing navigates: the page stays on the room's URL, now its invite
  // screen, rewound to the entry the room was entered on. A rejoin from there
  // puts a guard of its own over it, and a later leave leaves nothing behind.
  if (playerId && code && typeof window !== "undefined") {
    leaveRoomHistory(historyPortFor(window), { code, seat: playerId }, () => {});
  }
}

/**
 * The name this client plays under.
 *
 * Always the account's: a guest is handed one on their first visit and renames
 * it explicitly, and a registered player is their username. Keeping a second
 * copy in the game store is what previously let the two drift apart on a fresh
 * device, where the local copy was empty but the account had a name.
 */
/**
 * Reconcile the color in Settings with the one on the account.
 *
 * The account is the durable copy: it is the only place another player's view
 * of this name can read a color from, and it is what a second device inherits
 * instead of the color that device happened to generate. So an account that
 * has a color wins, and Settings adopts it.
 *
 * An account with no color is a player who chose one before it was ever
 * stored, or who has never opened Settings; their local choice is pushed up
 * once so their name looks the same on their profile as it does in a room.
 * A stored color outside the palette counts as none: the server re-rolls it
 * at the seat now (#571), so adopting it here would only show a color the
 * room is about to disagree with. Guests are skipped - their grey is the cue
 * that the name is unclaimed.
 */
function reconcileNameColor(user: AuthUser | null): void {
  if (!user || user.isAnonymous) return;
  const settings = useSettingsStore.getState();
  if (user.nameColor && isPaletteColor(user.nameColor)) {
    if (user.nameColor !== settings.nameColor) settings.setNameColor(user.nameColor);
    return;
  }
  if (!settings.nameColor) return;
  void apiRequest<AuthUser>("/api/auth/name-color", {
    method: "POST",
    body: { nameColor: settings.nameColor },
  })
    .then((updated) => useAuthStore.setState({ user: updated }))
    // Nothing here is worth interrupting the player over: the color still
    // applies locally and the next load tries again.
    .catch(() => {});
}

/** What `/api/auth/me` answers: the account, and - for a registered one - its
    settings, which the first paint needs and used to cost a request of their
    own (#983). Only the account is kept in the store. */
type MeResponse = AuthUser & { settings?: AccountSettings };

async function loadRegisteredSettings(
  user: AuthUser | null,
  known?: AccountSettings,
): Promise<void> {
  if (!user || user.isAnonymous) return;
  try {
    const settings = known ?? await fetchUserSettings();
    // Fetched before they are applied, so an account's language is in place
    // by the time the paint this read is holding goes ahead (R-I18N-06).
    await loadCatalogue(settings.locale);
    applyAccountSettings(settings);
  } catch {
    // Settings are an enhancement, not an authentication dependency. Keep the
    // local copy when offline and try again on the next account resolution.
  }
}

let inFlightProvision: Promise<AuthUser> | null = null;
// Bumped by every identity transition - provisioned, registered, logged in,
// logged out. A `fetchMe` that began before one of those answers truthfully
// about a moment that has since passed, and applying it would undo the
// transition: logging out starts such a read, and naming yourself or signing
// in during it would be erased by its result.
let identityVersion = 0;
let inFlightFetchMe: Promise<AuthUser | null> | null = null;
// Whether the last `/me` read failed to reach the server, as opposed to the
// server answering that nobody is signed in (review of #1065): the two are
// both `null` to a caller, and only the second is a sign-out.
let lastReadFailed = false;

/**
 * Whether this visitor still has to choose a name before they can play.
 *
 * Naming is what provisions the account now, and the server needs one to open
 * a room and a valid nickname to seat anybody - so an unnamed visitor who
 * reaches a Create or Join button reaches a refusal. The first-run block asks
 * for the name; these controls wait for it.
 */
export function needsIdentity(user: AuthUser | null): boolean {
  return !user || (user.isAnonymous && (!user.displayName || Boolean(user.nameInUse)));
}

export function currentPlayerName(): string {
  return useAuthStore.getState().user?.displayName ?? "";
}

/**
 * Record who this browser is now, and that it changed.
 *
 * Every path that installs or removes an identity goes through here, so a
 * read still in flight from before the change can tell that its answer is
 * stale. Bumping in only one of them is how the others got clobbered.
 */
function installIdentity(
  set: (partial: Partial<AuthStore>) => void,
  user: AuthUser | null,
): void {
  identityVersion += 1;
  set({ user, hasResolved: true });
}

export const useAuthStore = create<AuthStore>((set, get) => {
  /**
   * Become this account, whatever proved it.
   *
   * A password and a passkey answer different questions and land in the same
   * place, and what follows is the same either way — which is why it is one
   * function. A second sign-in path that only set the user looked right and
   * left the socket bound to the guest it replaced: the old seat stayed
   * occupied on the server, and everything live carried on under an identity
   * this browser no longer had.
   */
  const adopt = async (user: AuthUser): Promise<AuthUser> => {
    installIdentity(set, user);
    reconcileNameColor(user);
    await loadRegisteredSettings(user);
    releaseSeatBeforeIdentityChange();
    reconnectSocketAsNewIdentity();
    return user;
  };

  return {
  user: null,
  isLoading: false,
  hasResolved: false,
  nameDraft: "",

  fetchMe: async () => {
    // Single-flight. `/me` creates nothing any more - naming yourself does -
    // but it can rotate the session cookie, and two reads racing would each
    // set one. React StrictMode replays mount effects in development, which
    // makes that the normal case rather than a rare one. The first read adopts
    // the one `index.html` already started (#983).
    if (inFlightFetchMe) return inFlightFetchMe;

    set({ isLoading: true });
    const startedAt = identityVersion;
    lastReadFailed = false;
    inFlightFetchMe = (async () => {
      try {
        const { settings, ...user } = (await apiRequest<MeResponse | null>("/api/auth/me")) ?? {};
        const account = "id" in user ? (user as AuthUser) : null;
        if (identityVersion !== startedAt) {
          // Somebody was provisioned while this was in the air. They are the
          // truth; this answer describes a moment that has passed.
          set({ isLoading: false, hasResolved: true });
          return get().user;
        }
        set({ user: account, isLoading: false, hasResolved: true });
        reconcileNameColor(account);
        await loadRegisteredSettings(account, settings);
        return account;
      } catch {
        // Offline or the server is down. The app still works: play continues
        // without a durable identity rather than blocking on the account -
        // and with the one it already held, if any: a read that never
        // arrived says nothing about the account.
        lastReadFailed = true;
        const held = get().user;
        set({ user: held, isLoading: false, hasResolved: true });
        return held;
      } finally {
        inFlightFetchMe = null;
      }
    })();
    return inFlightFetchMe;
  },

  adoptFromServer: async (options) => {
    // A `/me` already in the air may predate the change this is asked to
    // notice; let it land, then read afresh.
    if (inFlightFetchMe) await inFlightFetchMe.catch(() => null);
    const before = get().user?.id ?? null;
    const account = await get().fetchMe();
    // A read that failed is not an answer: the identity, the seat and the
    // socket stay as they were rather than being given up as nobody's
    // (review of #1065). The next read settles it.
    if (lastReadFailed) return account;
    if ((account?.id ?? null) === before) {
      // The same account under a new session - a password change or reset
      // by this very browser - keeps its seat, but the socket handshook with
      // the session just revoked and remembers it: handshake again with the
      // cookie now in hand, so a later revocation of this session finds it.
      if (options?.rebindSocket) reconnectWithCurrentIdentity();
      return account;
    }
    // `fetchMe` has already installed the account, reconciled its colour and
    // loaded its settings; what it does not do is the transition - the bump
    // every in-flight read checks, the seat, the socket.
    installIdentity(set, account);
    releaseSeatBeforeIdentityChange();
    reconnectSocketAsNewIdentity();
    return account;
  },

  setNameDraft: (nameDraft) => set({ nameDraft }),

  ensureIdentity: async () => {
    const existing = get().user;
    if (existing && !needsIdentity(existing)) return existing;
    const chosen = get().nameDraft.trim();
    const invalid = chosen ? nicknameError(chosen) : ui.authStore.chooseANameToPlay;
    if (invalid) throw new IdentityRequiredError(invalid);
    return get().setDisplayName(chosen);
  },

  applyPendingRole: (pendingRole) =>
    set((state) => (state.user ? { user: { ...state.user, pendingRole } } : {})),

  markNameInUse: () =>
    set((state) => (state.user?.isAnonymous ? { user: { ...state.user, nameInUse: true } } : {})),

  setDisplayName: async (displayName) => {
    const had = get().user;
    // Single-flight while there is no account yet, for the reason `fetchMe`
    // used to need it: two cookieless POSTs both create one, and whichever
    // Set-Cookie lands second discards the account the first made - along
    // with the name that was just chosen. Two callers can easily reach here
    // at once now, because pressing Create or Join provisions from the same
    // draft the first-run block's own button does.
    if (!had && inFlightProvision) return inFlightProvision;
    const request = (async () => {
      const user = await apiRequest<AuthUser>("/api/auth/display-name", {
        method: "POST",
        body: { displayName },
      });
      installIdentity(set, user);
      // The socket resolved its account at the handshake and will not look
      // again, so it shakes hands once more whenever the account underneath
      // it changed. Not just when there was none before: a cached guest whose
      // session has expired or been revoked is handed a *different* account
      // here, and the socket would otherwise stay bound to the dead one.
      if (had?.id !== user.id) reconnectWithCurrentIdentity();
      return user;
    })();
    if (!had) {
      inFlightProvision = request;
      try {
        return await request;
      } finally {
        inFlightProvision = null;
      }
    }
    return request;
  },

  setNameColor: async (nameColor) => {
    useSettingsStore.getState().setNameColor(nameColor);
    const user = await apiRequest<AuthUser>("/api/auth/name-color", {
      method: "POST",
      body: { nameColor },
    });
    set({ user, hasResolved: true });
    return user;
  },

  register: async (username, password, email) => {
    const user = await apiRequest<AuthUser>("/api/auth/register", {
      method: "POST",
      body: {
        username,
        password,
        settings: currentSettingsPayload(),
        ...(email ? { email } : {}),
      },
    });
    installIdentity(set, user);
    reconcileNameColor(user);
    await loadRegisteredSettings(user);
    reconnectSocketAsNewIdentity();
    return user;
  },

  login: async (username, password, code) => {
    const user = await apiRequest<AuthUser>("/api/auth/login", {
      method: "POST",
      body: code ? { username, password, code } : { username, password },
    });
    return adopt(user);
  },

  signInWithPasskey: async () => {
    // The server's response carries the account, so there is nothing to read
    // back: the assertion identified it, which is the point of a
    // discoverable credential.
    const { user } = await assertPasskey();
    return adopt(user);
  },

  logout: async () => {
    // This tab's own sign-out closes its socket from the server side too
    // (#1007), and that notice must not read as "signed out elsewhere".
    signingOut = true;
    try {
      await apiRequest("/api/auth/logout", { method: "POST" });
    } catch {
      // A refusal, a proxy page, or no network: the cookie may still stand,
      // but this browser is told it is out either way, and the read below
      // brings the account back if the server still knows it (#1007).
    }
    installIdentity(set, null);
    releaseSeatBeforeIdentityChange();
    // Provision the replacement guest *before* reconnecting: the handshake
    // reads the cookie once, so bouncing first would bind the socket to no
    // account and it would never see the cookie that arrives moments later.
    await useAuthStore.getState().fetchMe();
    reconnectSocketAsNewIdentity();
    signingOut = false;
  },
  };
});

let signingOut = false;

/** Whether this tab is in the middle of its own sign-out (#1007): the server
closes its socket with a `session_superseded` notice like any revoked
session's, and only a notice this tab did not ask for is news. */
export function isSigningOut(): boolean {
  return signingOut;
}

// A request that found this tab signed out re-reads the account, so the
// header stops claiming an account whose session another device revoked
// (#1007). Only while the store holds one: a guest's 401 is expected.
onUnexpectedSignOut(() => {
  if (useAuthStore.getState().user) void useAuthStore.getState().adoptFromServer();
});
