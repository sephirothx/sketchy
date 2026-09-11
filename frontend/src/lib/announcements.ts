/** What the room's own lines say, read out of the catalogue.

An announcement is one event reaching every seat at once, and the seats need
not share a language. The server sends a code and typed parameters; each
client renders the sentence for its own reader, so two players in one room see
the same fact in their own words and the transcript stays one transcript
(R-I18N-03).

The words live in the catalogue (`content/ui`) with everything else the
interface says. What stays here is the vocabulary the wire uses and the two
readers on top of it. */
import { ui } from "../content/ui/index.ts";
import type { ChatMessage } from "../types.ts";

/** Mirrors `Announcement` in `backend/app/announcements.py`, member for
    member; `tests/test_wire_contract.py` fails when the two drift. */
export type AnnouncementCode =
  | "nickname_changed"
  | "joined_as_player"
  | "kicked_by_vote"
  | "marked_afk_by_vote"
  | "restart_vote_started"
  | "restart_vote_passed"
  | "restart_vote_rejected"
  | "restart_vote_expired"
  | "restart_vote_abandoned"
  | "restart_cancelled"
  | "game_restarted_by_vote"
  | "hint_letter_found"
  | "hint_letter_missing"
  | "guess_very_close"
  | "guess_some_words_correct";

/** Mirrors `RestartCancelReason`, for the same reason. */
export type RestartCancelReason =
  | "server_update"
  | "too_few_players"
  | "prompt_lists_unavailable"
  | "everybody_left";

export type AnnouncementParams = Record<string, unknown>;

/** The words for a room-authored line, or null if this is not one. */
export function announcementText(message: ChatMessage): string | null {
  const code = message.code;
  if (!code || !(code in ui.announcements)) return null;
  return ui.announcements[code as AnnouncementCode](message.params ?? {});
}

/** What to show for any chat line: the room's own words, or the player's.

A player's line is their own text and is never translated - what somebody
typed is what everybody sees. */
export function chatLineText(message: ChatMessage): string {
  return announcementText(message) ?? message.text ?? "";
}
