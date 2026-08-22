import { apiRequest } from "./api";
import {
  useSettingsStore,
  type AppTheme,
  type BrushCursorStyle,
  type KeyBindings,
} from "../store/settingsStore";

export interface AccountSettings {
  theme: AppTheme;
  soundEffects: boolean;
  confettiEffects: boolean;
  volume: number;
  brushCursor: BrushCursorStyle;
  keyBindings: KeyBindings;
  colorblindSafeColors: boolean;
  autoClearChatOnGuess: boolean;
  customBrushPresets: Record<string, unknown>[];
  createdAt?: string;
  updatedAt?: string;
}

export function currentSettingsPayload(): AccountSettings {
  const settings = useSettingsStore.getState();
  return {
    theme: settings.theme,
    soundEffects: settings.soundEffects,
    confettiEffects: settings.confettiEffects,
    volume: settings.volume,
    brushCursor: settings.brushCursor,
    keyBindings: settings.keyBindings,
    colorblindSafeColors: settings.colorblindSafeColors,
    autoClearChatOnGuess: settings.autoClearChatOnGuess,
    customBrushPresets: settings.customBrushPresets,
  };
}

export function applyAccountSettings(settings: AccountSettings): void {
  const local = useSettingsStore.getState();
  local.setAllSettings({
    ...settings,
    nameColor: local.nameColor,
  });
}

export function fetchUserSettings(): Promise<AccountSettings> {
  return apiRequest("/api/users/me/settings");
}

export function patchUserSettings(
  settings: AccountSettings,
): Promise<AccountSettings> {
  return apiRequest("/api/users/me/settings", {
    method: "PATCH",
    body: settings,
  });
}
