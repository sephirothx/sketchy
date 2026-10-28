import { useNavigate } from "react-router-dom";
import { FavoriteControl } from "./FavoriteControl";
import { favoriteSetTo, isFavorite, withFavorite } from "../lib/favorites";
import { refusalSentence } from "../lib/refusals.ts";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import { useMyFavorites } from "../store/favoritesStore";
import { ui } from "../content/ui/index.ts";

/**
 * The Favorite star on a drawing that is in the Gallery (#1501): a post in
 * the feed, the drawing's own page, and the viewer opened from somebody's
 * favorites. Any registered account may favorite any of them (R-PIN-01) -
 * the drawing is public already, so for a stranger it shares nothing - and
 * the control is the signed-in player's own shelf, through the one queue
 * every Favorite control writes through (R-PIN-09).
 */
export function GalleryFavoriteControl({
  turnId,
  look = "icon",
  onChanged,
}: {
  turnId: string;
  look?: "icon" | "labelled";
  /** Told once a write has landed, for a page whose own state it may change. */
  onChanged?: () => void;
}) {
  const navigate = useNavigate();
  const { notify } = useToast();
  const user = useAuthStore((state) => state.user);
  const favorites = useMyFavorites();
  const registered = Boolean(user && !user.isAnonymous);
  return (
    <FavoriteControl
      favorited={isFavorite(favorites.turnIds, turnId)}
      eligibility={registered ? "offered" : "hidden"}
      disabled={!favorites.ready || favorites.pending}
      look={look}
      addLabel={ui.favoriteControl.addThisDrawingToYourFavorites}
      onToggle={async () => {
        const adding = !isFavorite(favorites.turnIds, turnId);
        // A seventh is refused before the request, with the server's sentence.
        if (adding && withFavorite(favorites.turnIds, turnId) === null) {
          notify(refusalSentence("favorites_full"), "error");
          return;
        }
        const done = await favorites.mutate((current) => favoriteSetTo(current, turnId, adding));
        if (!done) {
          notify(refusalSentence("favorites_full"), "error");
          return;
        }
        onChanged?.();
        if (adding) {
          notify(ui.favoriteControl.addedToYourFavorites, "success", undefined, {
            label: ui.favoriteControl.seeThem,
            onClick: () => navigate("/profile"),
          });
        }
      }}
    />
  );
}
