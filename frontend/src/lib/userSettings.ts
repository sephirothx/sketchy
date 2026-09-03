import { apiRequest } from "./api";
import {
  useSettingsStore,
  type AppTheme,
  type BrushCursorStyle,
  type KeyBindings,
} from "../store/settingsStore";

/** The preferences that follow a registered player across devices (R-SET-01). */
export interface AccountSettings {
  theme: AppTheme;
  soundEffects: boolean;
  confettiEffects: boolean;
  volume: number;
  brushCursor: BrushCursorStyle;
  keyBindings: KeyBindings;
  colorblindSafeColors: boolean;
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

/** Partial by design: every row applies on its own, so it is sent on its own. */
export function patchUserSettings(
  settings: Partial<AccountSettings>,
): Promise<AccountSettings> {
  return apiRequest("/api/users/me/settings", {
    method: "PATCH",
    body: settings,
  });
}
