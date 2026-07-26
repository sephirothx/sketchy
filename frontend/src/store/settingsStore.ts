import { create } from "zustand";

export type PenCursorStyle = "crosshair" | "circle";

export interface KeyBindings {
  pen: string[];
  fill: string[];
  eraser: string[];
  rectangle: string[];
  triangle: string[];
  ellipse: string[];
  brushDecrease: string[];
  brushIncrease: string[];
  undo: string[];
}

export const DEFAULT_KEY_BINDINGS: KeyBindings = {
  pen: ["p", "1"],
  fill: ["f", "2"],
  eraser: ["e", "3"],
  rectangle: ["r", "4"],
  triangle: ["t", "5"],
  ellipse: ["c", "6"],
  brushDecrease: ["["],
  brushIncrease: ["]"],
  undo: ["z"],
};

export const DEFAULT_PEN_CURSOR: PenCursorStyle = "crosshair";

export const ACTION_LABELS: Record<keyof KeyBindings, string> = {
  pen: "Pen Tool",
  fill: "Fill Tool",
  eraser: "Eraser Tool",
  rectangle: "Rectangle Tool",
  triangle: "Triangle Tool",
  ellipse: "Ellipse Tool",
  brushDecrease: "Decrease Brush Size",
  brushIncrease: "Increase Brush Size",
  undo: "Undo Stroke",
};

function loadStoredKeyBindings(): KeyBindings {
  try {
    const raw = localStorage.getItem("sketchy_keybindings");
    if (!raw) return DEFAULT_KEY_BINDINGS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_KEY_BINDINGS, ...parsed };
  } catch {
    return DEFAULT_KEY_BINDINGS;
  }
}

function loadStoredPenCursor(): PenCursorStyle {
  try {
    const raw = localStorage.getItem("sketchy_pencursor");
    if (raw === "circle" || raw === "crosshair") return raw;
    return DEFAULT_PEN_CURSOR;
  } catch {
    return DEFAULT_PEN_CURSOR;
  }
}

interface SettingsStore {
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  keyBindings: KeyBindings;
  penCursor: PenCursorStyle;
  setAllSettings: (payload: { keyBindings: KeyBindings; penCursor: PenCursorStyle }) => void;
  setKeyBinding: (action: keyof KeyBindings, keys: string[]) => void;
  setPenCursor: (penCursor: PenCursorStyle) => void;
  resetKeyBindings: () => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  isSettingsOpen: false,
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  keyBindings: loadStoredKeyBindings(),
  penCursor: loadStoredPenCursor(),
  setAllSettings: ({ keyBindings, penCursor }) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(keyBindings));
      localStorage.setItem("sketchy_pencursor", penCursor);
      return { keyBindings, penCursor };
    }),
  setKeyBinding: (action, keys) =>
    set((state) => {
      const updated = { ...state.keyBindings, [action]: keys };
      localStorage.setItem("sketchy_keybindings", JSON.stringify(updated));
      return { keyBindings: updated };
    }),
  setPenCursor: (penCursor) =>
    set(() => {
      localStorage.setItem("sketchy_pencursor", penCursor);
      return { penCursor };
    }),
  resetKeyBindings: () =>
    set(() => {
      localStorage.removeItem("sketchy_keybindings");
      return { keyBindings: DEFAULT_KEY_BINDINGS };
    }),
}));
