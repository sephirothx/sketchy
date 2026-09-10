import { announcementText } from "./announcements.ts";
import type { ChatMessage } from "../types";

/** Live-region text for essential chat events. Restricted guesses are never announced. */
export function chatAnnouncement(message: ChatMessage): string | null {
  if (message.restricted) return null;
  // The client's own got-it event line carries no nickname; its text already
  // reads as a sentence.
  if (message.correct) {
    return message.nickname
      ? `${message.nickname} guessed the prompt.`
      : announcementText(message) ?? message.text ?? null;
  }
  // A room-authored line is announced in the reader's own language, like the
  // rest of it: a screen reader has no fallback a sighted player does not
  // also have (R-A11Y-03).
  if (message.system) return announcementText(message) ?? message.text ?? null;
  return null;
}
