import { create } from "zustand";

import {
  BRUSH_CURSOR_KEY,
  LEGACY_BRUSH_CURSOR_KEY,
  migrateKeyBindings,
  readStoredBrushCursor,
} from "./settingsMigrations.ts";

export type BrushCursorStyle = "crosshair" | "circle";
export type AppTheme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export interface KeyBindings {
  brush: string[];
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
  brush: ["p", "1"],
  fill: ["f", "2"],
  eraser: ["e", "3"],
  rectangle: ["r", "4"],
  triangle: ["t", "5"],
  ellipse: ["c", "6"],
  brushDecrease: ["["],
  brushIncrease: ["]"],
  undo: ["z"],
};

export const DEFAULT_BRUSH_CURSOR: BrushCursorStyle = "crosshair";
export const DEFAULT_THEME: AppTheme = "system";
export const NAME_COLOR_PALETTE = [
  "#e11d48",
  "#c2410c",
  "#a16207",
  "#15803d",
  "#0f766e",
  "#0369a1",
  "#4f46e5",
  "#7e22ce",
  "#be185d",
] as const;

export function randomNameColor(exclude?: string): string {
  const choices = NAME_COLOR_PALETTE.filter((color) => color !== exclude);
  return choices[Math.floor(Math.random() * choices.length)] ?? NAME_COLOR_PALETTE[0];
}

export const ACTION_LABELS: Record<keyof KeyBindings, string> = {
  brush: "Brush tool",
  fill: "Fill tool",
  eraser: "Eraser tool",
  rectangle: "Rectangle tool",
  triangle: "Triangle tool",
  ellipse: "Ellipse tool",
  brushDecrease: "Decrease brush size",
  brushIncrease: "Increase brush size",
  undo: "Undo stroke",
};

export function getSystemTheme(): ResolvedTheme {
  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

export function resolveTheme(theme: AppTheme): ResolvedTheme {
  return theme === "system" ? getSystemTheme() : theme;
}

export function applyThemeToDocument(theme: AppTheme) {
  if (typeof document === "undefined") return;
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

function loadStoredKeyBindings(): KeyBindings {
  try {
    const raw = localStorage.getItem("sketchy_keybindings");
    if (!raw) return DEFAULT_KEY_BINDINGS;
    return migrateKeyBindings(JSON.parse(raw), DEFAULT_KEY_BINDINGS);
  } catch {
    return DEFAULT_KEY_BINDINGS;
  }
}

function loadStoredBrushCursor(): BrushCursorStyle {
  try {
    const raw = readStoredBrushCursor(localStorage);
    if (raw === "circle" || raw === "crosshair") return raw;
    return DEFAULT_BRUSH_CURSOR;
  } catch {
    return DEFAULT_BRUSH_CURSOR;
  }
}

function loadStoredTheme(): AppTheme {
  try {
    const raw = localStorage.getItem("sketchy_theme");
    if (raw === "dark" || raw === "light" || raw === "system") return raw;
  } catch {
    // Fall through to the default system preference when storage is unavailable.
  }

  return DEFAULT_THEME;
}

function loadStoredFlag(key: string, defaultValue = true): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? defaultValue : raw !== "false";
  } catch {
    return defaultValue;
  }
}

function loadStoredBrushPresets(): Record<string, unknown>[] {
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem("sketchy_custombrushpresets") ?? "[]",
    );
    return Array.isArray(parsed)
      ? parsed.filter((item): item is Record<string, unknown> => (
        typeof item === "object" && item !== null && !Array.isArray(item)
      )).slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

function loadStoredVolume(): number {
  try {
    const raw = localStorage.getItem("sketchy_volume");
    if (raw !== null) {
      const parsed = parseFloat(raw);
      if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) return parsed;
    }
    return 0.7;
  } catch {
    return 0.7;
  }
}

function loadStoredNameColor(): string {
  try {
    const raw = localStorage.getItem("sketchy_namecolor");
    if (raw && /^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toLowerCase();
    const generated = randomNameColor();
    localStorage.setItem("sketchy_namecolor", generated);
    return generated;
  } catch {
    return randomNameColor();
  }
}

interface SettingsStore {
  isSettingsOpen: boolean;
  openSettings: () => void;
  closeSettings: () => void;
  keyBindings: KeyBindings;
  brushCursor: BrushCursorStyle;
  theme: AppTheme;
  confettiEffects: boolean;
  soundEffects: boolean;
  volume: number;
  colorblindSafeColors: boolean;
  autoClearChatOnGuess: boolean;
  customBrushPresets: Record<string, unknown>[];
  nameColor: string;
  setAllSettings: (payload: {
    keyBindings: KeyBindings;
    brushCursor: BrushCursorStyle;
    theme?: AppTheme;
    confettiEffects?: boolean;
    soundEffects?: boolean;
    volume?: number;
    colorblindSafeColors?: boolean;
    autoClearChatOnGuess?: boolean;
    customBrushPresets?: Record<string, unknown>[];
    nameColor: string;
  }) => void;
  setKeyBinding: (action: keyof KeyBindings, keys: string[]) => void;
  setBrushCursor: (brushCursor: BrushCursorStyle) => void;
  setNameColor: (nameColor: string) => void;
  setTheme: (theme: AppTheme) => void;
  setConfettiEffects: (enabled: boolean) => void;
  setSoundEffects: (enabled: boolean) => void;
  setVolume: (volume: number) => void;
  setColorblindSafeColors: (enabled: boolean) => void;
  setAutoClearChatOnGuess: (enabled: boolean) => void;
  resetKeyBindings: () => void;
}

const initialTheme = loadStoredTheme();
applyThemeToDocument(initialTheme);

export const useSettingsStore = create<SettingsStore>((set) => ({
  isSettingsOpen: false,
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  keyBindings: loadStoredKeyBindings(),
  brushCursor: loadStoredBrushCursor(),
  theme: initialTheme,
  confettiEffects: loadStoredFlag("sketchy_confettieffects"),
  soundEffects: loadStoredFlag("sketchy_soundeffects"),
  volume: loadStoredVolume(),
  colorblindSafeColors: loadStoredFlag("sketchy_colorblindsafecolors", false),
  autoClearChatOnGuess: loadStoredFlag("sketchy_autoclearchatonguess"),
  customBrushPresets: loadStoredBrushPresets(),
  nameColor: loadStoredNameColor(),
  setAllSettings: ({
    keyBindings,
    brushCursor,
    theme = DEFAULT_THEME,
    confettiEffects = true,
    soundEffects = true,
    volume = 0.7,
    colorblindSafeColors = false,
    autoClearChatOnGuess = true,
    customBrushPresets = [],
    nameColor,
  }) =>
    set(() => {
      localStorage.setItem("sketchy_keybindings", JSON.stringify(keyBindings));
      localStorage.setItem(BRUSH_CURSOR_KEY, brushCursor);
      localStorage.removeItem(LEGACY_BRUSH_CURSOR_KEY);
      localStorage.setItem("sketchy_theme", theme);
      localStorage.setItem("sketchy_confettieffects", String(confettiEffects));
      localStorage.setItem("sketchy_soundeffects", String(soundEffects));
      localStorage.setItem("sketchy_volume", String(volume));
      localStorage.setItem("sketchy_colorblindsafecolors", String(colorblindSafeColors));
      localStorage.setItem("sketchy_autoclearchatonguess", String(autoClearChatOnGuess));
      localStorage.setItem("sketchy_custombrushpresets", JSON.stringify(customBrushPresets));
      localStorage.setItem("sketchy_namecolor", nameColor);
      applyThemeToDocument(theme);
      return {
        keyBindings,
        brushCursor,
        theme,
        confettiEffects,
        soundEffects,
        volume,
        colorblindSafeColors,
        autoClearChatOnGuess,
        customBrushPresets,
        nameColor,
      };
    }),
  setKeyBinding: (action, keys) =>
    set((state) => {
      const updated = { ...state.keyBindings, [action]: keys };
      localStorage.setItem("sketchy_keybindings", JSON.stringify(updated));
      return { keyBindings: updated };
    }),
  setBrushCursor: (brushCursor) =>
    set(() => {
      localStorage.setItem(BRUSH_CURSOR_KEY, brushCursor);
      localStorage.removeItem(LEGACY_BRUSH_CURSOR_KEY);
      return { brushCursor };
    }),
  setNameColor: (nameColor) =>
    set(() => {
      localStorage.setItem("sketchy_namecolor", nameColor);
      return { nameColor };
    }),
  setTheme: (theme) =>
    set(() => {
      localStorage.setItem("sketchy_theme", theme);
      applyThemeToDocument(theme);
      return { theme };
    }),
  setConfettiEffects: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_confettieffects", String(enabled));
      return { confettiEffects: enabled };
    }),
  setSoundEffects: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_soundeffects", String(enabled));
      return { soundEffects: enabled };
    }),
  setVolume: (volume) =>
    set(() => {
      localStorage.setItem("sketchy_volume", String(volume));
      return { volume };
    }),
  setColorblindSafeColors: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_colorblindsafecolors", String(enabled));
      return { colorblindSafeColors: enabled };
    }),
  setAutoClearChatOnGuess: (enabled) =>
    set(() => {
      localStorage.setItem("sketchy_autoclearchatonguess", String(enabled));
      return { autoClearChatOnGuess: enabled };
    }),
  resetKeyBindings: () =>
    set(() => {
      localStorage.removeItem("sketchy_keybindings");
      return { keyBindings: DEFAULT_KEY_BINDINGS };
    }),
}));

if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const syncSystemTheme = () => {
    if (useSettingsStore.getState().theme === "system") {
      applyThemeToDocument("system");
    }
  };
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", syncSystemTheme);
  } else if (typeof media.addListener === "function") {
    media.addListener(syncSystemTheme);
  }
}
