import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * Settings as a URL (R-SET-06).
 *
 * It opens over whatever page you were on - changing the volume mid-turn must
 * not unmount a live room - but it is still a route, so it can be linked,
 * bookmarked and pointed at from an answer to a support question. The page
 * underneath is the one recorded in `settingsBackground` when it was opened;
 * somebody who arrives on the URL itself gets the lobby behind it.
 */
export const SETTINGS_SECTIONS = ["account", "appearance", "sound", "shortcuts"] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];
export const DEFAULT_SETTINGS_SECTION: SettingsSection = "account";

/** Case-insensitive, because react-router matches routes that way. */
const SETTINGS_PATH = /^\/settings(\/|$)/i;

export function isSettingsPath(pathname: string): boolean {
  return SETTINGS_PATH.test(pathname);
}

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

export interface SettingsLocationState {
  /** The path Settings was opened from, drawn underneath it until it closes. */
  settingsBackground?: string;
}

export function useOpenSettings(): (section?: SettingsSection) => void {
  const navigate = useNavigate();
  const location = useLocation();
  const from = `${location.pathname}${location.search}`;
  return useCallback(
    (section: SettingsSection = DEFAULT_SETTINGS_SECTION) => {
      if (isSettingsPath(location.pathname)) {
        // Already open: switch section without stacking a second history
        // entry, and keep the page it was opened over.
        navigate(settingsPath(section), { replace: true, state: location.state });
        return;
      }
      navigate(settingsPath(section), { state: { settingsBackground: from } });
    },
    [navigate, from, location.pathname, location.state],
  );
}
