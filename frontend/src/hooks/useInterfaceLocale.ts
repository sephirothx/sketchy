import { useCallback } from "react";

import { queueSettingsSync } from "../lib/accountSettingsSync";
import type { Locale } from "../lib/interfaceLocale.ts";
import { useSettingsStore } from "../store/settingsStore";

/** The language the interface is read in, and the one way to change it.

Two places offer it - Settings, and the lobby header, where somebody who cannot
read the language they landed in arrives first - so both call this rather than
each keeping its own copy of the two steps: the switch, and the account save
that makes it follow the player to another device (R-I18N-06). */
export function useInterfaceLocale(): [Locale, (next: Locale) => void] {
  const locale = useSettingsStore((state) => state.locale);
  const setLocale = useSettingsStore((state) => state.setLocale);
  const choose = useCallback(
    (next: Locale) => {
      setLocale(next);
      queueSettingsSync({ locale: next });
    },
    [setLocale],
  );
  return [locale, choose];
}
