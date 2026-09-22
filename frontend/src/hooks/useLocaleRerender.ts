import { useSettingsStore } from "../store/settingsStore";

/** Re-render when the interface language changes, for a memoised component.

The words are read at render from `ui`, a live binding React cannot see
change (`content/ui/index.ts`). Everything used to reach a language switch
through the App root, which subscribes to the locale and re-renders the whole
tree - but a `memo` boundary with unchanged props skips that re-render and
keeps the old words (#987 review). Such a component calls this, and passes
the result to any memoised row it renders, so the switch reaches it too. */
export function useLocaleRerender(): string {
  return useSettingsStore((state) => state.locale);
}
