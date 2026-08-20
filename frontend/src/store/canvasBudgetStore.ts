import { create } from "zustand";

interface CanvasBudgetStore {
  /**
   * Whether another fill still fits in this turn's replay budget.
   *
   * The canvas owns the drawing history and the toolbar owns the tools, and
   * they are siblings - this is the channel between them, the same shape as
   * `canvasCommands` in the other direction.
   */
  fillAvailable: boolean;
  setFillAvailable: (available: boolean) => void;
}

export const useCanvasBudgetStore = create<CanvasBudgetStore>((set) => ({
  fillAvailable: true,
  // Published after every action, but it only changes once a turn at most, so
  // hold the existing state identity rather than waking every subscriber.
  setFillAvailable: (fillAvailable) =>
    set((state) => (state.fillAvailable === fillAvailable ? state : { fillAvailable })),
}));
