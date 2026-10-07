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
      notify(
        refusalText(
          failure,
          shared
            ? ui.shareControl.thatDrawingCouldNotBeShared
            : ui.shareControl.thatCouldNotBeTakenBack,
        ),
        "error",
      );
    } finally {
      setBusy(false);
    }
  }

  // One button whatever it offers, so pressing it keeps the focus where it
  // was: a button swapped for another under the pointer drops it.
  const button =
    offer === "share"
      ? { label: ui.shareControl.share, title: ui.shareControl.shareThisDrawing, pressed: false, shared: true, testId: "share-toggle", look: "btn-secondary" }
      : offer === "unshare"
        ? { label: ui.shareControl.shared, title: ui.shareControl.takeBackYourShare, pressed: true, shared: false, testId: "share-toggle", look: "btn-secondary is-shared" }
        : offer === "takeOut"
          ? { label: ui.shareControl.takeOut, title: ui.shareControl.takeThisDrawingOut, pressed: undefined, shared: false, testId: "share-take-out", look: "btn-ghost" }
          : null;

  return (
    <div className="share-control" data-testid="share-control">
      {button && (
        <button
          type="button"
          className={`btn ${button.look} btn-compact share-control-button`}
          aria-pressed={button.pressed}
          title={button.title}
          disabled={busy || disabled}
          data-testid={button.testId}
          onClick={() => void press(button.shared)}
        >
          {button.look !== "btn-ghost" && <ImageIcon size={14} />}
          {button.label}
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
