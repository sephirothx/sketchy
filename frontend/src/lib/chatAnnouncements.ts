import type { ChatMessage } from "../types";

/** Live-region text for essential chat events. Restricted guesses are never announced. */
export function chatAnnouncement(message: ChatMessage): string | null {
  if (message.restricted) return null;
  if (message.correct) return `${message.nickname} guessed the word.`;
  if (message.system) return message.text;
  return null;
}
