import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { queueSettingsSync } from "../lib/accountSettingsSync";
import type { Locale } from "../lib/interfaceLocale.ts";
import { isPublicPath, localePath, splitLocalePath } from "../lib/localePath";
import { overlayBackgroundOf } from "../lib/overlayRoutes";
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
  const { pathname, search, hash, state } = useLocation();
  const navigate = useNavigate();
  const choose = useCallback(
    (next: Locale) => {
      // Over Settings, the page is the one the overlay was opened from.
      const background = overlayBackgroundOf(state);
      const [page, query = ""] = (background ?? pathname).split("?");
      const { path } = splitLocalePath(page);
      // Saved to the account only once the words are here and showing: a
      // language whose chunk could not be fetched would otherwise follow the
      // player to every device while this one stays in the old language.
      // The address follows for the same reason (review of #1462): on a
      // public page the choice is also a page, the same one at its address
      // in that language, and only once the switch - which remembers the
      // choice - has worked.
      void setLocale(next).then((applied) => {
        if (!applied) return;
        queueSettingsSync({ locale: next });
        if (!isPublicPath(path)) return;
        const there = localePath(path, next) + (query && `?${query}`);
        navigate(
          background ? pathname + search : there + search + hash,
          background
            ? { replace: true, state: { overlayBackground: there, overlayMoved: true } }
            : { replace: true },
        );
      });
    },
    [setLocale, pathname, search, hash, state, navigate],
  );
  return [locale, choose];
}
