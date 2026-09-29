import { useRef, useState } from "react";
import { emitWithAck, socketRequestErrorMessage } from "../lib/socket";
import type { AckResponse } from "../types";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/**
 * A spectator in a waiting room: that they are watching, and the open seat
 * they can take (`become_player`), or that there is none.
 *
 * One component for both homes. The desktop draws it under the players
 * panel; a phone hides that panel in the waiting room (its roster grid says
 * who is here), and the row lived nowhere else, so a spectator on a phone
 * could not take a free seat and was never told they were spectating (#1269).
 * The roster draws it now as well.
 */
export function SpectatorPromotion({ playerSpaceAvailable }: { playerSpaceAvailable: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  async function becomePlayer() {
    if (busy || !playerSpaceAvailable) return;
    // Read now: the offer is gone once the seat is taken, and the focus with
    // it. It lands on the heading of the list the player has just joined.
    const heading = rootRef.current?.closest("section")?.querySelector<HTMLElement>("h2");
    setBusy(true);
    setError(null);
    try {
      const response = await emitWithAck<AckResponse>("become_player", {});
      if (!response.ok) setError(refusalText(response, ui.roomPlayersPanel.couldNotJoinAsPlayer));
      else requestAnimationFrame(() => heading?.focus());
    } catch (requestError) {
      setError(socketRequestErrorMessage(requestError, ui.roomPlayersPanel.joinAsAPlayer));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="spectator-promotion" data-testid="spectator-promotion" ref={rootRef}>
      <p>
        <b>{ui.roomPlayersPanel.youAreSpectating}</b>{" "}
        {playerSpaceAvailable ? ui.roomPlayersPanel.aPlayerSeatIsOpen : ui.roomPlayersPanel.noPlayerSeatsOpen}
      </p>
      <button
        type="button"
        className="btn btn-primary btn-compact"
        disabled={!playerSpaceAvailable || busy}
        onClick={() => void becomePlayer()}
      >
        {busy ? ui.roomPlayersPanel.joining : ui.roomPlayersPanel.joinAsPlayer}
      </button>
      {error && (
        <p className="spectator-promotion-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
