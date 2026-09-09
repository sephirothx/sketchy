import { useCallback } from "react";
import { useLocation } from "react-router-dom";

import { isSettingsPath } from "../lib/overlayRoutes";
import { useOpenOverlay } from "./useOverlayRoute";

/**
 * Settings as a URL (R-SET-06).
 *
 * It opens over whatever page you were on - changing the volume mid-turn must
 * not unmount a live room - but it is still a route, so it can be linked,
 * bookmarked and pointed at from an answer to a support question. The page
 * underneath is the one recorded in `overlayBackground` when it was opened;
 * somebody who arrives on the URL itself gets the lobby behind it.
 *
 * The drawn-over-the-page half of that is in `useOverlayRoute.ts`, which
 * Friends shares (R-FRIEND-10). What stays here is what only Settings has:
 * sections, and the URL that names one.
 */
export const SETTINGS_SECTIONS = ["account", "appearance", "sound", "shortcuts"] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];
export const DEFAULT_SETTINGS_SECTION: SettingsSection = "account";

export function settingsPath(section: SettingsSection): string {
  return `/settings/${section}`;
}

/**
 * Which section a settings URL names; the first one for `/settings` alone or
 * for a section that does not exist, so a mistyped link still opens Settings
 * rather than the not-found page.
 *
 * Read from the path rather than `useParams`: the overlay renders beside
 * `<Routes>`, which is drawing the page underneath, so it sits in no matched
 * route and has no params of its own.
 */
export function sectionFromPath(pathname: string): SettingsSection {
  const value = pathname.split("/")[2]?.toLowerCase();
  return SETTINGS_SECTIONS.find((section) => section === value) ?? DEFAULT_SETTINGS_SECTION;
}

export function useOpenSettings(): (section?: SettingsSection) => void {
  const openOverlay = useOpenOverlay();
  const location = useLocation();
  const onSettings = isSettingsPath(location.pathname);
  return useCallback(
    (section: SettingsSection = DEFAULT_SETTINGS_SECTION) => {
      // Already open: switching section replaces, so Back leaves Settings
      // rather than walking through the sections visited. `useOpenOverlay`
      // replaces for any overlay-to-overlay move, which is the same thing.
      openOverlay(settingsPath(section), { replace: onSettings });
    },
    [openOverlay, onSettings],
  );
}
