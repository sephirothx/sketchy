import { useState } from "react";
import { ImageIcon } from "./icons";
import { useToast } from "../lib/toast";
import { refusalText } from "../lib/refusals.ts";
import { playerNameClass, playerNameStyle } from "../lib/playerName";
import type { ShareCredit, ShareOffer } from "../lib/shares";
import { ui } from "../content/ui/index.ts";
import { fill } from "../content/ui/slots.tsx";
import "../styles/lazy/shares.css";

interface ShareControlProps {
  offer: ShareOffer;
  credit: ShareCredit;
  /** Share (true) or take back (false). Rejections are announced here. */
  onShare: (shared: boolean) => Promise<void>;
  /** Not yet, though offered: the state it would act on is still loading. */
  disabled?: boolean;
}

/**
 * Share to Gallery, beside a drawing (#1430): offered only where pressing it
 * can work (the R-REACT-13 rule), with a line saying whose share put it there.
 *
 * Four faces. Share, for anyone who may. Shared - pressed - for somebody who
 * shared it and did not draw it, which takes their share back. Take out, for
 * its drawer once it is in, which takes it out for everybody (R-SHARE-04).
 * And, for everybody else after that, a line saying its drawer kept it out,
 * so a missing button is not a mystery.
 */
export function ShareControl({ offer, credit, onShare, disabled = false }: ShareControlProps) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  if (offer === "hidden" && credit.kind === "none") return null;

  async function press(shared: boolean) {
    if (busy || disabled) return;
    setBusy(true);
    try {
      await onShare(shared);
    } catch (failure) {
      notify(refusalText(failure, ui.shareControl.thatDrawingCouldNotBeShared), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="share-control" data-testid="share-control">
      {offer === "share" && (
        <button
          type="button"
          className="btn btn-secondary btn-compact share-control-button"
          aria-pressed={false}
          title={ui.shareControl.shareThisDrawing}
          disabled={busy || disabled}
          data-testid="share-toggle"
          onClick={() => void press(true)}
        >
          <ImageIcon size={14} />
          {ui.shareControl.share}
        </button>
      )}
      {offer === "unshare" && (
        <button
          type="button"
          className="btn btn-secondary btn-compact share-control-button is-shared"
          aria-pressed={true}
          title={ui.shareControl.takeBackYourShare}
          disabled={busy || disabled}
          data-testid="share-toggle"
          onClick={() => void press(false)}
        >
          <ImageIcon size={14} />
          {ui.shareControl.shared}
        </button>
      )}
      {offer === "takeOut" && (
        <button
          type="button"
          className="btn btn-ghost btn-compact share-control-button"
          title={ui.shareControl.takeThisDrawingOut}
          disabled={busy || disabled}
          data-testid="share-take-out"
          onClick={() => void press(false)}
        >
          {ui.shareControl.takeOut}
        </button>
      )}
      {offer === "withdrawn" && (
        <span className="share-control-line" data-testid="share-withdrawn">
          {ui.shareControl.theDrawerKeptItOut}
        </span>
      )}
      {credit.kind !== "none" && (
        <span className="share-control-line" data-testid="share-credit">
          {creditLine(credit)}
        </span>
      )}
    </div>
  );
}

function creditLine(credit: ShareCredit) {
  switch (credit.kind) {
    case "you":
      return ui.shareControl.inTheGallerySharedByYou;
    case "drawer":
      return ui.shareControl.inTheGallerySharedByTheDrawer;
    case "player":
      return fill(ui.shareControl.inTheGallerySharedBy, {
        sharer: (
          <strong
            className={playerNameClass(credit.isAnonymous)}
            style={playerNameStyle(credit.nameColor ?? undefined, credit.isAnonymous)}
          >
            {credit.name}
          </strong>
        ),
      });
    default:
      return ui.shareControl.inTheGallery;
  }
}
