import { useState } from "react";
import { PinIcon } from "./icons";
import { useToast } from "../lib/toast";
import { refusalText } from "../lib/refusals.ts";
import type { PinEligibility } from "../lib/pinnedDrawings";
import { ui } from "../content/ui/index.ts";

interface PinControlProps {
  pinned: boolean;
  eligibility: PinEligibility;
  /**
   * Not yet, though offered: the shelf is still being read, or another
   * control's write is in flight. Every control is disabled by the same
   * store flags, so two cannot be pressed together (R-PIN-02).
   */
  disabled?: boolean;
  /** Toggle: pin when not pinned, unpin when pinned. Rejections are announced here. */
  onToggle: () => Promise<void>;
}

/**
 * The Pin / Pinned toggle beside a drawing (#440), offered only where
 * pressing it can work (R-PIN-09): a registered player, in a public game,
 * looking at a drawing that was kept. Everyone else sees nothing - the
 * reaction control beside it already tells a guest about accounts, and a
 * second line saying the same would be noise.
 */
export function PinControl({ pinned, eligibility, disabled = false, onToggle }: PinControlProps) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  if (eligibility !== "offered") return null;

  async function toggle() {
    if (busy || disabled) return;
    setBusy(true);
    try {
      await onToggle();
    } catch (failure) {
      notify(refusalText(failure, ui.pinControl.thatDrawingCouldNotBePinned), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className={`btn btn-secondary btn-compact pin-control${pinned ? " is-pinned" : ""}`}
      aria-pressed={pinned}
      aria-label={pinned ? ui.pinControl.unpinThisDrawing : ui.pinControl.pinThisDrawing}
      title={pinned ? ui.pinControl.unpinThisDrawing : ui.pinControl.pinThisDrawing}
      disabled={busy || disabled}
      data-testid="pin-toggle"
      onClick={() => void toggle()}
    >
      <PinIcon size={14} />
      {pinned ? ui.pinControl.pinned : ui.pinControl.pin}
    </button>
  );
}
