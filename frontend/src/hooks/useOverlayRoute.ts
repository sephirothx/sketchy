import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  isOverlayPath,
  overlayBackgroundOf,
  type OverlayLocationState,
} from "../lib/overlayRoutes";

/** Opening and closing an overlay route - the two halves both overlays share.

The rules over the paths are in `lib/overlayRoutes.ts`, which imports nothing,
so they stay reachable by a test runner with no bundler behind it. */

/** Navigate to an overlay path, remembering the page it was opened over.

`replace` is for an overlay switching between its own sub-paths: the rail is
one screen, and Back should leave the overlay rather than walk through the
sections visited. Opening one from a page pushes, so Back closes it.

An overlay opened while another is already open keeps the page underneath
rather than recording the first overlay as its background - closing the second
would otherwise reopen the first over a page nobody asked for. */
export function useOpenOverlay(): (
  path: string,
  options?: { replace?: boolean },
) => void {
  const navigate = useNavigate();
  const location = useLocation();
  const from = `${location.pathname}${location.search}`;
  const onOverlay = isOverlayPath(location.pathname);
  return useCallback(
    (path: string, options?: { replace?: boolean }) => {
      if (onOverlay) {
        navigate(path, { replace: options?.replace ?? true, state: location.state });
        return;
      }
      navigate(path, {
        replace: options?.replace ?? false,
        state: { overlayBackground: from } satisfies OverlayLocationState,
      });
    },
    [navigate, from, onOverlay, location.state],
  );
}

/** Close the overlay, back to the page it was drawn over.

`navigate(-1)` rather than a push to the recorded path, so the history does not
grow an entry every time somebody opens and closes it. Somebody who arrived on
the URL itself has nothing to go back to and gets the lobby, which is what was
drawn underneath them anyway. */
export function useCloseOverlay(): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  const background = overlayBackgroundOf(location.state);
  return useCallback(() => {
    if (background) navigate(-1);
    else navigate("/", { replace: true });
  }, [navigate, background]);
}
