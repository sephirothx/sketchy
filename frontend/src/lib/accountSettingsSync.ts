import { createSettingsSync } from "./settingsSync";
import { patchUserSettings } from "./userSettings";
import { useAuthStore } from "../store/authStore";

/**
 * The one sync the app uses, bound to the account API and the auth store.
 * The factory it is built from is pure and lives in `settingsSync.ts`, so the
 * merging and ordering rules are tested without a store or a socket.
 */
const accountSettingsSync = createSettingsSync({
  send: patchUserSettings,
  canSync: () => {
    const user = useAuthStore.getState().user;
    return Boolean(user) && !user?.isAnonymous;
  },
  /** How long a change waits for company before it is sent. */
  delayMs: 400,
});

export const queueSettingsSync = accountSettingsSync.queue;
export const flushSettingsSync = accountSettingsSync.flush;
export const onSettingsSyncError = accountSettingsSync.onError;
