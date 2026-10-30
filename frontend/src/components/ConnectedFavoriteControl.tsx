import { FavoriteControl } from "./FavoriteControl";
import { ApiError } from "../lib/api";
import { useToast } from "../lib/toast";
import { refusalSentence } from "../lib/refusals.ts";
import { isFavorite, favoriteEligibility, favoriteSetTo, withFavorite } from "../lib/favorites";
import { sendDrawingShare } from "../lib/shareRequests";
import { satIn } from "../lib/shares";
import { selectMe, useGameStore } from "../store/gameStore";
import { useAuthStore } from "../store/authStore";
import { useMyFavorites } from "../store/favoritesStore";

interface ConnectedFavoriteControlProps {
  /** The drawing being shown, by turn id; nothing renders without one. */
  turnId: string | null | undefined;
  /** False for a recap entry whose bitmap the room gave up: nothing to favorite. */
  visible?: boolean;
  /** Who drew it, by seat token: the drawer may favorite - share - from any game. */
  drawerId?: string | null;
  /** Nothing was drawn: a blank canvas is not shared, so it is not favorited. */
  blank?: boolean;
}

/**
 * The Favorite control bound to the live room's game-over recap: the room says
 * whether the game is public, the seat whether I am a spectator, the account
 * whether I may favorite at all, and the shared store what is already favorited.
 *
 * The write goes to the finished game over REST. Between game over and the
 * history write landing the turn is not there yet (R-HIST-26), and the
 * route answers the same 404 it answers a stranger; here, on the screen the
 * game just ended on, that 404 means one thing, and is said as such.
 */
export function ConnectedFavoriteControl({
  turnId,
  visible = true,
  drawerId = null,
  blank = false,
}: ConnectedFavoriteControlProps) {
  // The recap's: the finished game's visibility, not the room's since.
  const isPublic = useGameStore((state) => state.lastGamePublic ?? state.isPublic);
  const playerId = useGameStore((state) => state.playerId);
  // The seat's tokens in this game: one who left and came back still sat in
  // it, and still drew what they drew, under the old one.
  const own = useGameStore((state) => state.ownSeatTokens);
  const withdrawn = useGameStore((state) =>
    turnId ? state.drawingShares[turnId]?.withdrawn ?? false : false,
  );
  // Somebody who arrived in the waiting room after the game is shown its
  // recap, and has nothing to favorite from it (R-PIN-01: only a game they sat in).
  const notASeatThatPlayed = useGameStore(
    (state) =>
      (selectMe(state)?.isSpectator ?? false)
      // By the game's seats, not its standings: a seat that left before the
      // end sat in it too.
      || !satIn(state.lastGameSeatTokens, state.ownSeatTokens),
  );
  const user = useAuthStore((state) => state.user);
  const favorites = useMyFavorites();
  const { notify } = useToast();
  if (!turnId) return null;
  const eligibility = favoriteEligibility({
    isRegistered: Boolean(user && !user.isAnonymous),
    isSpectator: notASeatThatPlayed,
    isPublicGame: isPublic,
    open: visible,
    isDrawer: Boolean(drawerId) && (drawerId === playerId || own.includes(drawerId ?? "")),
    blank,
    withdrawn,
  });
  const favorited = isFavorite(favorites.turnIds, turnId);
  return (
    <FavoriteControl
      favorited={favorited}
      eligibility={eligibility}
      disabled={!favorites.ready || favorites.pending}
      onToggle={async () => {
        const adding = !favorited;
        try {
          // A favorite is a share (R-PIN-03). Shared first, the way the Share
          // control does it, so the room hears it and the drawer - who may be
          // right here, looking at the same recap - is not sent a notice about
          // something they watched happen (R-SHARE-09); the favorite write then
          // finds the share already made.
          if (adding) {
            // Refused before anything is shared: a seventh favorite that shared
            // the drawing anyway would publish what the press was told no to.
            if (withFavorite(favorites.turnIds, turnId) === null) {
              notify(refusalSentence("favorites_full"), "error");
              return;
            }
            const answer = await sendDrawingShare(turnId, true);
            if (answer.shares) {
              useGameStore.getState().applyDrawingShare({
                turnId,
                shares: answer.shares,
                shareWithdrawn: answer.shareWithdrawn ?? false,
              });
            }
          }
          // Computed when the queue reaches it, from the list as it stands
          // then: a press that lands beside another cannot forget its favorite.
          // What the press asked is fixed here, so a list it never saw cannot
          // turn an add into a removal.
          const done = await favorites.mutate((current) => favoriteSetTo(current, turnId, adding));
          if (!done) notify(refusalSentence("favorites_full"), "error");
        } catch (failure) {
          if (failure instanceof ApiError && failure.status === 404) {
            notify(refusalSentence("game_still_saving"), "error");
            return;
          }
          throw failure;
        }
      }}
    />
  );
}
