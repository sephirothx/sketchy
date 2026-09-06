/** Where a guess made right now belongs, read from the game store.

Kept out of `socket.ts`, which the store must be free to import; this module
imports both and wires one to the other once. */
import { provideGuessScope } from "./socket";
import { useGameStore } from "../store/gameStore";

provideGuessScope(() => {
  const { code, currentTurnId } = useGameStore.getState();
  if (!code || !currentTurnId) return null;
  return { code, turnId: currentTurnId };
});

export { sendGuess } from "./socket";
