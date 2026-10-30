import { useState } from "react";
import { StarIcon } from "./icons";
import { useToast } from "../lib/toast";
import { refusalText } from "../lib/refusals.ts";
import type { FavoriteEligibility } from "../lib/favorites";
import { ui } from "../content/ui/index.ts";
import "../styles/lazy/profile.css";

interface FavoriteControlProps {
  favorited: boolean;
  eligibility: FavoriteEligibility;
  /**
   * Not yet, though offered: the shelf is still being read, or another
   * control's write is in flight. Every control is disabled by the same
   * store flags, so two cannot be pressed together (R-PIN-02).
   */
  disabled?: boolean;
  /** Toggle: favorite when not favorited, unfavorite when favorited. Rejections are announced here. */
  onToggle: () => Promise<void>;
}

/**
 * The favorite toggle beside a drawing (#440), in the viewer and in the game
 * history's rows: its icon alone, its name in the label and the tooltip.
 * Offered only where
 * pressing it can work (R-PIN-09): a registered player, in a public game,
 * looking at a drawing that was kept. Everyone else sees nothing - the
 * reaction control beside it already tells a guest about accounts, and a
 * second line saying the same would be noise.
 */
export function FavoriteControl({ favorited, eligibility, disabled = false, onToggle }: FavoriteControlProps) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  if (eligibility !== "offered") return null;

  async function toggle() {
    if (busy || disabled) return;
    setBusy(true);
    try {
      await onToggle();
    } catch (failure) {
      notify(refusalText(failure, ui.favoriteControl.thatDrawingCouldNotBeFavorited), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className={`btn btn-secondary btn-compact favorite-control${favorited ? " is-favorited" : ""}`}
      aria-pressed={favorited}
      aria-label={favorited ? ui.favoriteControl.unfavoriteThisDrawing : ui.favoriteControl.favoriteThisDrawing}
      title={favorited ? ui.favoriteControl.unfavoriteThisDrawing : ui.favoriteControl.favoriteThisDrawing}
      disabled={busy || disabled}
      data-testid="favorite-toggle"
      onClick={() => void toggle()}
    >
      <StarIcon size={18} />
    </button>
  );
}
