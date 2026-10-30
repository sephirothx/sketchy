import { createContext, useCallback, useContext } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  isOverlayPath,
  overlayBackgroundOf,
  type OverlayLocationState,
} from "../lib/overlayRoutes";
import { isSheetEntry } from "../lib/roomHistory";

/** Opening and closing an overlay route - the two halves both overlays share.

The rules over the paths are in `lib/overlayRoutes.ts`, which imports nothing,
so they stay reachable by a test runner with no bundler behind it. */

/** Navigate to an overlay path, remembering the page it was opened over.

`replace` is for an overlay switching between its own sub-paths: the rail is
one screen, and Back should leave the overlay rather than walk through the
sections visited. Opening one from a page pushes, so Back closes it.

An overlay opened while another is already open keeps the page underneath
rather than recording the first overlay as its background - closing the second
would otherwise reopen the first over a page nobody asked for.

Opened from a sheet or menu in a room, it takes the place of that surface's
history entry (R-UX-15): the menu closes as the overlay opens, and an entry
left beneath would make Back step over it and Forward bounce off it. */
export function useOpenOverlay(): (
  path: string,
  options?: { replace?: boolean },
) => void {
  const navigate = useNavigate();
  const location = useLocation();
  // The address as the browser has it: inside the page table the router's
  // has no language prefix (#1462), and closing must come back to it.
  const from = `${window.location.pathname}${location.search}`;
  const onOverlay = isOverlayPath(location.pathname);
  return useCallback(
    (path: string, options?: { replace?: boolean }) => {
      if (onOverlay) {
        navigate(path, { replace: options?.replace ?? true, state: location.state });
        return;
      }
      navigate(path, {
        replace: options?.replace ?? isSheetEntry(window.history.state),
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
drawn underneath them anyway.

The entry is read when the overlay closes, from the browser's history, not
from the render that made this callback. Escape holds the callback of an
earlier render until an effect hands it the next one, and choosing the
interface language moves the page behind Settings (#1462) in between: the
entry already said the page had moved, the callback still said it had not,
and closing went Back to the address the page had just left. A slow device
hit it, and a CI runner did, about once in three at 20x CPU throttling. */
export function useCloseOverlay(): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  return useCallback(() => {
    const state = (window.history.state?.usr ?? location.state) as OverlayLocationState | null;
    const background = overlayBackgroundOf(state);
    if (background && state?.overlayMoved === true) navigate(background, { replace: true });
    else if (background) navigate(-1);
    else navigate("/", { replace: true });
  }, [navigate, location.state]);
}

/** Whether an overlay route - Settings, Friends - is open over the page.

The page underneath is drawn against the location the overlay was opened from
(`AppRoutes`), so its own `useLocation()` cannot tell; this is how it asks. A
page that raises a dialog of its own waits while one is open: the lobby's
first-time languages question opened over Settings when a visitor named
themselves there, and its Done put the focus on Quick play behind the sheet
(review of #1265). */
export const OverlayOpenContext = createContext(false);

export function useOverlayOpen(): boolean {
  return useContext(OverlayOpenContext);
}
