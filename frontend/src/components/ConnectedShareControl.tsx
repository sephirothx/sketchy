import { ShareControl } from "./ShareControl";
import { sendDrawingShare } from "../lib/shareRequests";
import { mineAmong, shareCredit, shareOffer } from "../lib/shares";
import { useAuthStore } from "../store/authStore";
import { selectMe, useGameStore } from "../store/gameStore";
import { usePinsStore } from "../store/pinsStore";
import type { DrawingShareState } from "../types";

const NOT_SHARED: DrawingShareState = { shares: [], withdrawn: false };

interface ConnectedShareControlProps {
  /** The drawing being shown, by turn id; nothing renders without one. */
  turnId: string | null | undefined;
  /** Who drew it, by seat token. */
  drawerId: string | null | undefined;
  /** Kept, and something was drawn: a blank canvas is nothing to show. */
  shareable: boolean;
  /** From the recap: the finished game's own visibility, not the room's. */
  recap?: boolean;
  look?: "button" | "pill";
}

/**
 * The Share control bound to the live room (#1430): the turn results while
 * the game runs, and the recap after it. The room says whether the game is
 * public and who shared what, the seat whether this is a spectator, and the
 * account whether there is anything to keep a share against. The send goes
 * over the socket - the room's memory while the game is live, the finished
 * game's row from the recap - and its answer is applied at once, before the
 * room's broadcast of the same thing arrives.
 */
export function ConnectedShareControl({
  turnId,
  drawerId,
  shareable,
  recap = false,
  look = "button",
}: ConnectedShareControlProps) {
  const playerId = useGameStore((state) => state.playerId);
  // The seat's tokens in this game, the current one included: a player who
  // left and came back is still the one who drew, played and shared under
  // the old one, as the server already counts them (R-SHARE-02).
  const own = useGameStore((state) => state.ownSeatTokens);
  const isSpectator = useGameStore((state) => selectMe(state)?.isSpectator ?? false);
  const isPublic = useGameStore((state) =>
    recap ? state.lastGamePublic ?? state.isPublic : state.isPublic,
  );
  const players = useGameStore((state) => state.players);
  const state = useGameStore((s) => (turnId ? s.drawingShares[turnId] ?? NOT_SHARED : NOT_SHARED));
  const hasAccount = useAuthStore((s) => s.user !== null);
  // From the recap, only a seat that played the game: somebody who arrived
  // in the waiting room afterwards is shown it, and has nothing to share.
  const played = useGameStore((s) =>
    !recap
    || (s.finalScores ?? []).some(
      (entry) => entry.playerId === s.playerId || s.ownSeatTokens.includes(entry.playerId),
    ),
  );
  if (!turnId) return null;
  const isDrawer = Boolean(drawerId) && (drawerId === playerId || own.includes(drawerId ?? ""));
  const mine = mineAmong(state.shares, own, playerId);
  const offer = shareOffer({
    isDrawer,
    canAct: hasAccount && !isSpectator && playerId !== null && played,
    isPublicGame: isPublic,
    shareable,
    shares: state.shares,
    mine,
    withdrawn: state.withdrawn,
  });
  const credit = shareCredit(state.shares, {
    mine,
    drawer: drawerId ?? null,
    nameOf: (token) => {
      const player = players.find((candidate) => candidate.playerId === token);
      return player
        ? { name: player.nickname, nameColor: player.nameColor ?? null, isAnonymous: player.isAnonymous }
        : null;
    },
  });
  return (
    <ShareControl
      offer={offer}
      credit={credit}
      look={look}
      onShare={async (shared) => {
        const answer = await sendDrawingShare(turnId, shared);
        if (!shared) usePinsStore.getState().forget(turnId);
        if (answer.shares) {
          useGameStore.getState().applyDrawingShare({
            turnId,
            shares: answer.shares,
            shareWithdrawn: answer.shareWithdrawn ?? false,
          });
        }
      }}
    />
  );
}
