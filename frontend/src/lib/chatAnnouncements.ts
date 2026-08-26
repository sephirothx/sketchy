import type { ChatMessage } from "../types";

/** Live-region text for essential chat events. Restricted guesses are never announced. */
export function chatAnnouncement(message: ChatMessage): string | null {
  if (message.restricted) return null;
  // The client's own got-it event line carries no nickname; its text already
  // reads as a sentence.
  if (message.correct) {
    return message.nickname ? `${message.nickname} guessed the prompt.` : message.text;
  }
  if (message.system) return message.text;
  return null;
}
