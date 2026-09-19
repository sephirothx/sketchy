import { create } from "zustand";

import { checkCanvasReadback, type CanvasReadback } from "../lib/canvasReadback.ts";

/** Whether this tab's canvas reads back what was painted (`canvasReadback.ts`),
and whether the player has closed the lobby banner that says it does not.

Checked once on arrival and again on **Check again**: a player may allow the
site in their browser, or change the setting, without reloading. */
interface CanvasReadbackStore {
  status: CanvasReadback;
  /** The banner was closed; the room chip still says it (R-UX-15). */
  bannerDismissed: boolean;
  check: () => CanvasReadback;
  dismissBanner: () => void;
}

export const useCanvasReadbackStore = create<CanvasReadbackStore>((set) => ({
  status: "unknown",
  bannerDismissed: false,
  check: () => {
    const status = checkCanvasReadback();
    set({ status });
    return status;
  },
  dismissBanner: () => set({ bannerDismissed: true }),
}));
