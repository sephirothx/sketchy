import { create } from "zustand";
import { apiRequest, ApiError } from "../lib/api";
import { emitTransient, reconnectWithCurrentIdentity, socket } from "../lib/socket";
import { useGameStore } from "./gameStore";
import { isPaletteColor, useSettingsStore } from "./settingsStore";
import { nicknameError } from "../lib/roomEntryState";
import {
  applyAccountSettings,
  currentSettingsPayload,
  fetchUserSettings,
} from "../lib/userSettings";

export interface AuthUser {
  id: string;
  username: string | null;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  /** Decides which staff entries the menu offers. Never the authorization -
      every endpoint behind them checks the role again for itself. */
  role: "user" | "moderator" | "admin";
  createdAt: string | null;
  lastLoginAt: string | null;
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
   * Adopt a role the account's own socket room just announced.
   *
   * What the menu offers, and nothing else: the role has never been the
   * authorization here (R-ROLE-01), so this cannot open a door - it stops the
   * app from hiding one that has just been opened, or offering one that has
   * just been closed, until the next reload.
   *
   * Deliberately not an identity change. `installIdentity` bumps
   * `identityVersion` and the callers around it bounce the socket, because the
   * account underneath has changed; here it is the same account with a
   * different role, and bouncing would drop the player out of whatever they
   * are doing to learn something the socket already told them.
   */
  applyRole: (role: AuthUser["role"]) => void;
  setDisplayName: (displayName: string) => Promise<AuthUser>;
  setNameColor: (nameColor: string) => Promise<AuthUser>;
  register: (username: string, password: string, email?: string) => Promise<AuthUser>;
  login: (username: string, password: string) => Promise<AuthUser>;
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
  if (useGameStore.getState().playerId && socket.connected) {
    emitTransient("leave_room");
  }
  useGameStore.getState().clearSession();
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

async function loadRegisteredSettings(user: AuthUser | null): Promise<void> {
  if (!user || user.isAnonymous) return;
  try {
    applyAccountSettings(await fetchUserSettings());
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

/**
 * Whether this visitor still has to choose a name before they can play.
 *
 * Naming is what provisions the account now, and the server needs one to open
 * a room and a valid nickname to seat anybody - so an unnamed visitor who
 * reaches a Create or Join button reaches a refusal. The first-run block asks
 * for the name; these controls wait for it.
 */
export function needsIdentity(user: AuthUser | null): boolean {
  return !user || (user.isAnonymous && !user.displayName);
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

export const useAuthStore = create<AuthStore>((set, get) => ({
  user: null,
  isLoading: false,
  hasResolved: false,
  nameDraft: "",

  fetchMe: async () => {
    // Single-flight. GET /api/auth/me is the call that creates the account, so
    // two concurrent cookieless requests would mint two guests and race over
    // which cookie survives. React StrictMode replays mount effects in
    // development, which makes that the normal case rather than a rare one.
    if (inFlightFetchMe) return inFlightFetchMe;

    set({ isLoading: true });
    const startedAt = identityVersion;
    inFlightFetchMe = (async () => {
      try {
        const user = await apiRequest<AuthUser>("/api/auth/me");
        if (identityVersion !== startedAt) {
          // Somebody was provisioned while this was in the air. They are the
          // truth; this answer describes a moment that has passed.
          set({ isLoading: false, hasResolved: true });
          return get().user;
        }
        set({ user, isLoading: false, hasResolved: true });
        reconcileNameColor(user);
        await loadRegisteredSettings(user);
        return user;
      } catch {
        // Offline or the server is down. The app still works: play continues
        // without a durable identity rather than blocking on the account.
        set({ user: null, isLoading: false, hasResolved: true });
        return null;
      } finally {
        inFlightFetchMe = null;
      }
    })();
    return inFlightFetchMe;
  },

  applyRole: (role) =>
    set((state) => (state.user ? { user: { ...state.user, role } } : {})),

  setNameDraft: (nameDraft) => set({ nameDraft }),

  ensureIdentity: async () => {
    const existing = get().user;
    if (existing && !needsIdentity(existing)) return existing;
    const chosen = get().nameDraft.trim();
    const invalid = chosen ? nicknameError(chosen) : "Choose a name to play under.";
    if (invalid) throw new IdentityRequiredError(invalid);
    return get().setDisplayName(chosen);
  },

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

  login: async (username, password) => {
    const user = await apiRequest<AuthUser>("/api/auth/login", {
      method: "POST",
      body: { username, password },
    });
    installIdentity(set, user);
    reconcileNameColor(user);
    await loadRegisteredSettings(user);
    releaseSeatBeforeIdentityChange();
    reconnectSocketAsNewIdentity();
    return user;
  },

  logout: async () => {
    try {
      await apiRequest("/api/auth/logout", { method: "POST" });
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
    installIdentity(set, null);
    releaseSeatBeforeIdentityChange();
    // Provision the replacement guest *before* reconnecting: the handshake
    // reads the cookie once, so bouncing first would bind the socket to no
    // account and it would never see the cookie that arrives moments later.
    await useAuthStore.getState().fetchMe();
    reconnectSocketAsNewIdentity();
  },
}));
