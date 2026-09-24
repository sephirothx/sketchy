/** What a line typed into the room's input is: a guess, or chat.

A guess only while there is something to guess at (#1008): the drawing phase,
from a seat that may still guess. Every other line - the drawer's, a
spectator's, a correct guesser's, and anybody's while the drawer is choosing
a prompt - is chat. The panel used to send a guess whenever the room was
playing, scoped to the turn it last saw; while the drawer chose, that was
the previous turn, and the server dropped the line as one that outlived its
moment. */
export type ChatInputPurpose = "guess" | "chat";

export function inputPurposeFor(
  mode: "waiting" | "playing" | "game-end",
  canGuess: boolean,
): ChatInputPurpose {
  return mode === "playing" && canGuess ? "guess" : "chat";
}
