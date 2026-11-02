import { create } from "zustand";

import { apiRequest } from "../lib/api";
import {
  fetchSupportPlans,
  fetchSupporterStatus,
  type SupportPlans,
  type SupporterStatus,
} from "../lib/support";

interface SupportState {
  /** Undefined until asked; null on a deployment that sells nothing. */
  plans: SupportPlans | null | undefined;
  status: SupporterStatus | null;
  showMark: boolean;
  nudgeDismissed: boolean;
  loadPlans: () => Promise<void>;
  /** What `GET /api/auth/me` already said, so a page load costs no request. */
  applyAccount: (
    status: SupporterStatus | undefined,
    settings: { showSupporterMark?: boolean; supporterNudgeDismissed?: boolean } | undefined,
  ) => void;
  refresh: () => Promise<void>;
  setShowMark: (show: boolean) => Promise<void>;
  dismissNudge: () => Promise<void>;
}

async function patchSettings(body: Record<string, boolean>): Promise<void> {
  await apiRequest("/api/users/me/settings", { method: "PATCH", body });
}

export const useSupportStore = create<SupportState>((set, get) => ({
  plans: undefined,
  status: null,
  showMark: true,
  nudgeDismissed: false,
  loadPlans: async () => {
    if (get().plans !== undefined) return;
    try {
      set({ plans: await fetchSupportPlans() });
    } catch {
      // A 404 is a deployment with no tier; anything else hides the pitch for
      // this page load rather than showing one that cannot be bought.
      set({ plans: null });
    }
  },
  applyAccount: (status, settings) => {
    set({
      status: status ?? null,
      showMark: settings?.showSupporterMark ?? true,
      nudgeDismissed: settings?.supporterNudgeDismissed ?? false,
    });
  },
  refresh: async () => {
    try {
      const [status, settings] = await Promise.all([
        fetchSupporterStatus(),
        apiRequest<{ showSupporterMark: boolean; supporterNudgeDismissed: boolean }>(
          "/api/users/me/settings",
        ),
      ]);
      get().applyAccount(status, settings);
    } catch {
      // A guest, or no tier: what was known stands.
    }
  },
  setShowMark: async (show) => {
    const before = get().showMark;
    set({ showMark: show });
    try {
      await patchSettings({ showSupporterMark: show });
    } catch (error) {
      set({ showMark: before });
      throw error;
    }
  },
  dismissNudge: async () => {
    set({ nudgeDismissed: true });
    // Closed on this screen whatever the network does.
    await patchSettings({ supporterNudgeDismissed: true }).catch(() => undefined);
  },
}));
