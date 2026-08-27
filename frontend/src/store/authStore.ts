import { create } from "zustand";
import { apiRequest, ApiError } from "../lib/api";
import { emitTransient, reconnectWithCurrentIdentity, socket } from "../lib/socket";
import { useGameStore } from "./gameStore";
import { useSettingsStore } from "./settingsStore";
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
 * Guests are skipped - their grey is the cue that the name is unclaimed.
 */
function reconcileNameColor(user: AuthUser | null): void {
  if (!user || user.isAnonymous) return;
  const settings = useSettingsStore.getState();
  if (user.nameColor) {
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
    inFlightFetchMe = (async () => {
      try {
        const user = await apiRequest<AuthUser>("/api/auth/me");
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
    const user = await apiRequest<AuthUser>("/api/auth/display-name", {
      method: "POST",
      body: { displayName },
    });
    set({ user, hasResolved: true });
    // Naming is what provisions, so this is the moment a visitor stops being
    // nobody. The socket resolved its account at the handshake and will not
    // look again, so it has to shake hands once more or spend its life
    // anonymous - unable to open a room for a player who now has an account.
    if (!had) reconnectWithCurrentIdentity();
    return user;
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
    set({ user, hasResolved: true });
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
    set({ user, hasResolved: true });
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
    set({ user: null });
    releaseSeatBeforeIdentityChange();
    // Provision the replacement guest *before* reconnecting: the handshake
    // reads the cookie once, so bouncing first would bind the socket to no
    // account and it would never see the cookie that arrives moments later.
    await useAuthStore.getState().fetchMe();
    reconnectSocketAsNewIdentity();
  },
}));
