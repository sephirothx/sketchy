import { lazy, Suspense, useState, type ComponentType } from "react";

import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";
import { ui } from "../content/ui/index.ts";

const loadScratchPad = () => import("./ScratchPad");

/* The pad is the whole drawing surface - canvas, toolbar, the pixel pipeline -
   and it sits in this banner on every page, so importing it put all of that
   in the entry chunk (#475). It is fetched once the page has painted instead
   (`prefetchPlayRoutes`):
   by the time a connection drops it is here, and it has to be, because a
   page with no connection cannot fetch it then. If it never arrived, the
   button opens nothing rather than a crash page. */
const ScratchPadDialog = lazy(() =>
  loadScratchPad().then(
    (module) => ({ default: module.ScratchPadDialog }),
    (): { default: ComponentType<{ onClose: () => void }> } => ({ default: () => null }),
  ),
);

/**
 * The connection banner, outside a room. When to show it is `placeNotices`'s
 * call; `connected` here means "no banner", which keeps an open pad mounted.
 *
 * It offers the scratch pad (#829), the one thing a page can still do with no
 * connection behind it. The pad is kept open until it is closed, even after
 * the connection comes back and the banner goes: a drawing is not taken away
 * mid-stroke because the network recovered.
 */
export function ConnectionStatusBanner({
  status,
}: {
  status: ConnectionStatus;
}) {
  const [padOpen, setPadOpen] = useState(false);

  return (
    <>
      {status !== "connected" && (
        <div className={`connection-status-banner ${status === "failed" ? "reconnecting" : status}`}>
          <span role="status" aria-live="polite">{connectionStatusText(status)}</span>
          <button
            type="button"
            className="connection-status-pad-button"
            data-testid="open-scratch-pad"
            onClick={() => setPadOpen(true)}
          >
            {ui.scratchPad.drawWhileYouWait}
          </button>
        </div>
      )}
      <Suspense fallback={null}>
        {padOpen && <ScratchPadDialog onClose={() => setPadOpen(false)} />}
      </Suspense>
    </>
  );
}
