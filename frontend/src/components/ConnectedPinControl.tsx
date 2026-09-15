import { PinControl } from "./PinControl";
import { ApiError } from "../lib/api";
import { useToast } from "../lib/toast";
import { refusalSentence } from "../lib/refusals.ts";
import { isPinned, pinEligibility, withPin, withoutPin } from "../lib/pinnedDrawings";
import { selectMe, useGameStore } from "../store/gameStore";
import { useAuthStore } from "../store/authStore";
import { useMyPins } from "../store/pinsStore";

interface ConnectedPinControlProps {
  /** The drawing being shown, by turn id; nothing renders without one. */
  turnId: string | null | undefined;
  /** False for a recap entry whose bitmap the room gave up: nothing to pin. */
  visible?: boolean;
}

/**
 * The Pin control bound to the live room's game-over recap: the room says
 * whether the game is public, the seat whether I am a spectator, the account
 * whether I may pin at all, and the shared store what is already pinned.
 *
 * The write goes to the finished game over REST. Between game over and the
 * history write landing the turn is not there yet (R-HIST-26), and the
 * route answers the same 404 it answers a stranger; here, on the screen the
 * game just ended on, that 404 means one thing, and is said as such.
 */
export function ConnectedPinControl({ turnId, visible = true }: ConnectedPinControlProps) {
  const isPublic = useGameStore((state) => state.isPublic);
  const isSpectator = useGameStore((state) => selectMe(state)?.isSpectator ?? false);
  const user = useAuthStore((state) => state.user);
  const pins = useMyPins();
  const { notify } = useToast();
  if (!turnId) return null;
  const eligibility = pinEligibility({
    isRegistered: Boolean(user && !user.isAnonymous),
    isSpectator,
    isPublicGame: isPublic,
    open: visible,
  });
  const pinned = isPinned(pins.turnIds, turnId);
  return (
    <PinControl
      pinned={pinned}
      eligibility={eligibility}
      onToggle={async () => {
        const next = pinned ? withoutPin(pins.turnIds, turnId) : withPin(pins.turnIds, turnId);
        if (next === null) {
          notify(refusalSentence("pinned_drawings_full"), "error");
          return;
        }
        try {
          await pins.replace(next);
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
