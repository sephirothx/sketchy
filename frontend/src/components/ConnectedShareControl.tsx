import { ShareControl } from "./ShareControl";
import { sendDrawingShare } from "../lib/shareRequests";
import { shareCredit, shareOffer } from "../lib/shares";
import { useAuthStore } from "../store/authStore";
import { selectMe, useGameStore } from "../store/gameStore";
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
}: ConnectedShareControlProps) {
  const playerId = useGameStore((state) => state.playerId);
  const isSpectator = useGameStore((state) => selectMe(state)?.isSpectator ?? false);
  const isPublic = useGameStore((state) =>
    recap ? state.lastGamePublic ?? state.isPublic : state.isPublic,
  );
  const players = useGameStore((state) => state.players);
  const state = useGameStore((s) => (turnId ? s.drawingShares[turnId] ?? NOT_SHARED : NOT_SHARED));
  const hasAccount = useAuthStore((s) => s.user !== null);
  if (!turnId) return null;
  const isDrawer = Boolean(drawerId) && drawerId === playerId;
  const offer = shareOffer({
    isDrawer,
    canAct: hasAccount && !isSpectator && playerId !== null,
    isPublicGame: isPublic,
    shareable,
    shares: state.shares,
    mine: playerId,
    withdrawn: state.withdrawn,
  });
  const credit = shareCredit(state.shares, {
    mine: playerId,
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
      onShare={async (shared) => {
        const answer = await sendDrawingShare(turnId, shared);
        if (answer.shares) {
          useGameStore.getState().applyDrawingShare({
            turnId,
            playerId: playerId ?? "",
            nickname: "",
            shared,
            shares: answer.shares,
            shareWithdrawn: answer.shareWithdrawn ?? false,
          });
        }
      }}
    />
  );
}
