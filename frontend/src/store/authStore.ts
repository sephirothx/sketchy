import { create } from "zustand";
import { apiRequest, ApiError } from "../lib/api";
import { socket } from "../lib/socket";

export interface AuthUser {
  id: string;
  username: string | null;
  displayName: string;
  nameColor: string | null;
  isAnonymous: boolean;
  createdAt: string | null;
  lastLoginAt: string | null;
}

interface AuthStore {
  user: AuthUser | null;
  isLoading: boolean;
  /** True once fetchMe has settled, successfully or not. */
  hasResolved: boolean;
  fetchMe: () => Promise<AuthUser | null>;
  setDisplayName: (displayName: string) => Promise<AuthUser>;
  register: (username: string, password: string) => Promise<AuthUser>;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
}

/**
 * The socket reads the session cookie once, at handshake time, so it cannot
 * notice that the cookie changed underneath it. Bouncing the transport makes
 * it handshake again as the new account; `useRoomSessionReconnect` then
 * rejoins the current room on `connect`, which is what updates the player's
 * identity in-game without a page reload.
 */
function reconnectSocketAsNewIdentity(): void {
  if (socket.connected) socket.disconnect();
  socket.connect();
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  isLoading: false,
  hasResolved: false,

  fetchMe: async () => {
    set({ isLoading: true });
    try {
      const user = await apiRequest<AuthUser>("/api/auth/me");
      set({ user, isLoading: false, hasResolved: true });
      return user;
    } catch {
      // Offline or the server is down. The app still works: play continues
      // without a durable identity rather than blocking on the account.
      set({ user: null, isLoading: false, hasResolved: true });
      return null;
    }
  },

  setDisplayName: async (displayName) => {
    const user = await apiRequest<AuthUser>("/api/auth/display-name", {
      method: "POST",
      body: { displayName },
    });
    set({ user, hasResolved: true });
    return user;
  },

  register: async (username, password) => {
    const user = await apiRequest<AuthUser>("/api/auth/register", {
      method: "POST",
      body: { username, password },
    });
    set({ user, hasResolved: true });
    reconnectSocketAsNewIdentity();
    return user;
  },

  login: async (username, password) => {
    const user = await apiRequest<AuthUser>("/api/auth/login", {
      method: "POST",
      body: { username, password },
    });
    set({ user, hasResolved: true });
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
    reconnectSocketAsNewIdentity();
    // A fresh guest identity is provisioned by the next /me call.
    await useAuthStore.getState().fetchMe();
  },
}));
