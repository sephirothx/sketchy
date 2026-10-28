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
  /** The star alone (the viewer, a history row, a Gallery post), or with its
      word beside it where there is room for one (a drawing's Gallery page). */
  look?: "icon" | "labelled";
  /** What adding it says, for a drawing that is in the Gallery already and
      so is not shared by being favorited (#1501). */
  addLabel?: string;
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
export function FavoriteControl({
  favorited,
  eligibility,
  disabled = false,
  onToggle,
  look = "icon",
  addLabel = ui.favoriteControl.favoriteThisDrawing,
}: FavoriteControlProps) {
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

  const label = favorited ? ui.favoriteControl.unfavoriteThisDrawing : addLabel;
  return (
    <button
      type="button"
      className={`btn btn-secondary btn-compact favorite-control${favorited ? " is-favorited" : ""}`}
      aria-pressed={favorited}
      // The star alone is named by its label; with its word beside it, by
      // that word, so what is said is what is seen (WCAG 2.5.3).
      aria-label={look === "icon" ? label : undefined}
      title={label}
      disabled={busy || disabled}
      data-testid="favorite-toggle"
      onClick={() => void toggle()}
    >
      <StarIcon size={18} />
      {look === "labelled" && (
        <span>{favorited ? ui.favoriteControl.inYourFavorites : ui.favoriteControl.favorite}</span>
      )}
    </button>
  );
}
