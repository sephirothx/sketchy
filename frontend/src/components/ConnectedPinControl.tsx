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
      disabled={!pins.ready || pins.pending}
      onToggle={async () => {
        try {
          // Computed when the queue reaches it, from the list as it stands
          // then: a press that lands beside another cannot forget its pin.
          const done = await pins.mutate((current) =>
            isPinned(current, turnId) ? withoutPin(current, turnId) : withPin(current, turnId),
          );
          if (!done) notify(refusalSentence("pinned_drawings_full"), "error");
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
