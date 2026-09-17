import { useState } from "react";

import { ScratchPadDialog } from "./ScratchPad";
import { connectionStatusText, type ConnectionStatus } from "../lib/connectionStatus";
import { ui } from "../content/ui/index.ts";

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
      {padOpen && <ScratchPadDialog onClose={() => setPadOpen(false)} />}
    </>
  );
}
