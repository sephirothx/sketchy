import { useState } from "react";
import { ImageIcon } from "./icons";
import { ConfirmationDialog } from "./ConfirmationDialog";
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
  /** `pill` sits beside the reaction control in the turn results, in its
      look, with the credit in its tooltip instead of a line beside it.
      `viewer` is the same pill as an icon alone, at the size of the drawing
      viewer's other buttons, named by its short word first (#1497). */
  look?: "button" | "pill" | "viewer";
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
 *
 * Taking it out asks first: it ends every other player's share and pin of
 * it, and nobody but its drawer can put it back.
 */
export function ShareControl({
  offer,
  credit,
  onShare,
  disabled = false,
  look = "button",
}: ShareControlProps) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
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

  function choose(shared: boolean, takesOut: boolean) {
    if (busy || disabled) return;
    if (takesOut) setConfirming(true);
    else void press(shared);
  }

  const confirmation = confirming && (
    <ConfirmationDialog
      title={ui.shareControl.takeOutTitle}
      description={ui.shareControl.takeOutDescription}
      confirmLabel={ui.shareControl.takeOutConfirm}
      onCancel={() => setConfirming(false)}
      onConfirm={() => {
        setConfirming(false);
        void press(false);
      }}
    />
  );

  if (look === "pill" || look === "viewer") {
    // Nothing to press, but the drawing is in the gallery: the viewer still
    // says so, as the button look's credit line did (R-SHARE-07).
    if (offer === "hidden" && look === "viewer" && credit.kind !== "none") {
      const said = creditText(credit) ?? ui.shareControl.inTheGallery;
      return (
        <span className="reaction-toggle share-pill is-inert" role="img" aria-label={said} title={said}>
          <span className="share-pill-icon">
            <ImageIcon size={18} />
          </span>
        </span>
      );
    }
    if (offer === "hidden") return null;
    return (
      <>
        <SharePill
          offer={offer}
          credit={credit}
          busy={busy || disabled}
          inViewer={look === "viewer"}
          onPress={(shared) => choose(shared, offer === "takeOut")}
        />
        {confirmation}
      </>
    );
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
          onClick={() => choose(button.shared, offer === "takeOut")}
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
      {confirmation}
    </div>
  );
}

/**
 * The turn results' Share: a second pill beside the reaction control, in its
 * look, pressed - the reaction's own ring - while the viewer's share or their
 * drawing is in the Gallery. One line of copy would not fit beside it, so
 * whose share put it there is in its tooltip; the drawer learns the name from
 * the notice as well. After its drawer takes it out it stays, inert, so the
 * pill nobody can press still says why.
 */
function SharePill({
  offer,
  credit,
  busy,
  inViewer = false,
  onPress,
}: {
  offer: Exclude<ShareOffer, "hidden">;
  credit: ShareCredit;
  busy: boolean;
  /** The viewer's button: the icon at its size, named by the short word. */
  inViewer?: boolean;
  onPress: (shared: boolean) => void;
}) {
  const pressed = offer === "unshare" || offer === "takeOut";
  const inert = offer === "withdrawn";
  const action =
    offer === "share"
      ? ui.shareControl.share
      : offer === "unshare"
        ? ui.shareControl.takeBackYourShare
        : offer === "takeOut"
          ? ui.shareControl.takeThisDrawingOut
          : ui.shareControl.theDrawerKeptItOut;
  const said = creditText(credit);
  const label = said && !inert ? `${said}\n${action}` : action;
  // In the viewer its short word starts its name, so a voice command that
  // says the button's word - "Share" - finds it; the rest follows it.
  const word = offer === "unshare" ? ui.shareControl.shared : offer === "takeOut" ? ui.shareControl.takeOut : ui.shareControl.share;
  const name = inViewer ? (inert ? `${word}\n${action}` : said ? `${word}\n${said}` : word) : label;
  return (
    <button
      type="button"
      className={`reaction-toggle share-pill${pressed ? " has-mine" : ""}${inert ? " is-inert" : ""}`}
      aria-pressed={inert ? undefined : pressed}
      aria-disabled={inert || busy || undefined}
      aria-label={name}
      title={label}
      data-testid={offer === "takeOut" ? "share-take-out" : inert ? "share-withdrawn" : "share-toggle"}
      onClick={() => {
        if (inert || busy) return;
        onPress(offer === "share");
      }}
    >
      <span className="share-pill-icon">
        <ImageIcon size={inViewer ? 18 : 15} />
      </span>
    </button>
  );
}

/** The credit as plain text, for a tooltip: a title cannot hold a coloured name. */
function creditText(credit: ShareCredit): string | null {
  switch (credit.kind) {
    case "you":
      return ui.shareControl.inTheGallerySharedByYou;
    case "drawer":
      return ui.shareControl.inTheGallerySharedByTheDrawer;
    case "player":
      return ui.shareControl.inTheGallerySharedBy.replace("{sharer}", credit.name);
    case "someone":
      return ui.shareControl.inTheGallery;
    default:
      return null;
  }
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
