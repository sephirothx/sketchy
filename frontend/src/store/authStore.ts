import { create } from "zustand";
import type { User } from "../types";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  error: string | null;
  fetchMe: () => Promise<User | null>;
  register: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  login: (username: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  setUser: (user: User | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: false,
  error: null,

  fetchMe: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch("/api/auth/me", {
        credentials: "include",
      });
      if (!response.ok) {
        set({ user: null, isLoading: false });
        return null;
      }
      const data: User = await response.json();
      set({ user: data, isLoading: false });
      return data;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to fetch user";
      set({ user: null, isLoading: false, error: msg });
      return null;
    }
  },

  register: async (username: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          username,
          password,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        const errorMsg = data.detail || "Registration failed";
        set({ isLoading: false, error: errorMsg });
        return { ok: false, error: errorMsg };
      }
      set({ user: data, isLoading: false, error: null });
      return { ok: true };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      set({ isLoading: false, error: msg });
      return { ok: false, error: msg };
    }
  },

  login: async (username: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();
      if (!response.ok) {
        const errorMsg = data.detail || "Login failed";
        set({ isLoading: false, error: errorMsg });
        return { ok: false, error: errorMsg };
      }
      set({ user: data, isLoading: false, error: null });
      return { ok: true };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      set({ isLoading: false, error: msg });
      return { ok: false, error: msg };
    }
  },

  logout: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (response.ok) {
        const data = await response.json();
        set({ user: data.user, isLoading: false, error: null });
      } else {
        set({ user: null, isLoading: false });
      }
    } catch {
      set({ user: null, isLoading: false });
    }
  },

  setUser: (user: User | null) => set({ user }),
}));
