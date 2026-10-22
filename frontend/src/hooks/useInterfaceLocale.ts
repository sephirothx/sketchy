import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { queueSettingsSync } from "../lib/accountSettingsSync";
import { rememberLocale, type Locale } from "../lib/interfaceLocale.ts";
import { isPublicPath, localePath, splitLocalePath } from "../lib/localePath";
import { useSettingsStore } from "../store/settingsStore";

/** The language the interface is read in, and the one way to change it.

Two places offer it - Settings, and the header of every page outside a room,
where somebody who cannot read the language they landed in arrives first (the
lobby, or the invite page a link lands on) - so both call this rather than
each keeping its own copy of the two steps: the switch, and the account save
that makes it follow the player to another device (R-I18N-06). */
export function useInterfaceLocale(): [Locale, (next: Locale) => void] {
  const locale = useSettingsStore((state) => state.locale);
  const setLocale = useSettingsStore((state) => state.setLocale);
  const { pathname, search, hash } = useLocation();
  const navigate = useNavigate();
  const choose = useCallback(
    (next: Locale) => {
      // On a public page the choice is also a page: the same one at its
      // address in that language (#1462). Remembered first, so leaving a
      // prefixed page for English finds English as the reader's own.
      const { path } = splitLocalePath(pathname);
      if (isPublicPath(path)) {
        rememberLocale(next);
        navigate(localePath(path, next) + search + hash, { replace: true });
      }
      // Saved to the account only once the words are here and showing: a
      // language whose chunk could not be fetched would otherwise follow the
      // player to every device while this one stays in the old language.
      void setLocale(next).then((applied) => {
        if (applied) queueSettingsSync({ locale: next });
      });
    },
    [setLocale, pathname, search, hash, navigate],
  );
  return [locale, choose];
}
