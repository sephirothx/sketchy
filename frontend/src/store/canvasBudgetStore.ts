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
  /**
   * Whether the brush and eraser can still be used this turn.
   *
   * Its own budget: points cost no replay work, so a turn can run out of
   * these while the fill budget is barely touched. Shapes and fill are
   * unaffected - neither spends a point.
   */
  strokeAvailable: boolean;
  setBudgets: (budgets: { fill: boolean; stroke: boolean }) => void;
}

export const useCanvasBudgetStore = create<CanvasBudgetStore>((set) => ({
  fillAvailable: true,
  strokeAvailable: true,
  // Published after every action, but each flips once a turn at most, so hold
  // the existing state identity rather than waking every subscriber.
  setBudgets: ({ fill, stroke }) =>
    set((state) => (
      state.fillAvailable === fill && state.strokeAvailable === stroke
        ? state
        : { fillAvailable: fill, strokeAvailable: stroke }
    )),
}));
