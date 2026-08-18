import { create } from "zustand";
import { apiRequest, ApiError } from "../lib/api";
import { socket } from "../lib/socket";
import type { User } from "../lib/username";

export type AuthDialog = "register" | "login" | null;

interface AuthState {
  user: User | null;
  isLoading: boolean;
  error: string | null;
  dialog: AuthDialog;
  fetchMe: () => Promise<User | null>;
  register: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  login: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  openDialog: (dialog: AuthDialog) => void;
  closeDialog: () => void;
}

function reconnectSocket() {
  if (socket.connected) socket.disconnect();
  socket.connect();
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: false,
  error: null,
  dialog: null,

  fetchMe: async () => {
    set({ isLoading: true, error: null });
    try {
      const data = await apiRequest<User>("/api/auth/me");
      set({ user: data, isLoading: false });
      return data;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to fetch user";
      set({ user: null, isLoading: false, error: msg });
      return null;
    }
  },

  register: async (username, password) => {
    set({ isLoading: true, error: null });
    try {
      const data = await apiRequest<User>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      set({ user: data, isLoading: false, error: null, dialog: null });
      reconnectSocket();
      return { ok: true };
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Registration failed";
      set({ isLoading: false, error: msg });
      return { ok: false, error: msg };
    }
  },

  login: async (username, password) => {
    set({ isLoading: true, error: null });
    try {
      const data = await apiRequest<User>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      set({ user: data, isLoading: false, error: null, dialog: null });
      reconnectSocket();
      return { ok: true };
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Login failed";
      set({ isLoading: false, error: msg });
      return { ok: false, error: msg };
    }
  },

  logout: async () => {
    set({ isLoading: true, error: null });
    try {
      await apiRequest<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
    } catch {
      // Still provision a fresh guest below.
    }
    try {
      const data = await apiRequest<User>("/api/auth/me");
      set({ user: data, isLoading: false, error: null, dialog: null });
    } catch {
      set({ user: null, isLoading: false });
    }
    reconnectSocket();
  },

  openDialog: (dialog) => set({ dialog, error: null }),
  closeDialog: () => set({ dialog: null, error: null }),
}));
