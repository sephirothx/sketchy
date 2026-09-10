/** What the room's own lines say, written here rather than on the server.

An announcement is one event reaching every seat at once, and the seats need
not share a language. The server sends a code and typed parameters; each
client renders the sentence for its own reader, so two players in one room see
the same fact in their own words and the transcript stays one transcript
(R-I18N-03).

The alternative - the server rendering per recipient - puts a translation
catalogue on the server and sends N payloads for one event. It is not a
cheaper version of this; it is a different, worse protocol.

Parameters are values: a nickname, a count, a reason slug. Never a fragment of
a sentence. `restart_cancelled` carries `reason: "server_update"` rather than
the clause English happens to put after *because*, because most languages do
not build that clause the same way. */
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

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function count(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** Why an approved restart never happened, as its own half-sentence.

Kept apart from the line so the sentence around it can be reordered freely -
a language that puts the reason first has somewhere to put it. */
function cancelReason(reason: unknown): string {
  switch (reason) {
    case "server_update":
      return "a server update is in progress";
    case "too_few_players":
      return "fewer than two active players remain";
    case "prompt_lists_unavailable":
      return "the prompt lists could not be loaded";
    case "everybody_left":
      return "everybody left before it could begin";
    default:
      return "it could no longer go ahead";
  }
}

/** Every line the room can say, and the words for it.

`Record<AnnouncementCode, …>` is exhaustive, so a code the server adds without
a sentence here fails the build rather than showing a player an empty line. */
const LINES: Record<AnnouncementCode, (params: AnnouncementParams) => string> = {
  nickname_changed: (p) =>
    `${text(p.previous)} is now known as ${text(p.nickname)}.`,
  joined_as_player: (p) => `${text(p.nickname)} joined as a player.`,
  kicked_by_vote: (p) => `${text(p.nickname)} was kicked by vote.`,
  marked_afk_by_vote: (p) => `${text(p.nickname)} was marked AFK by vote.`,

  restart_vote_started: (p) =>
    `${text(p.nickname)} started a vote to restart the game.`,
  restart_vote_passed: (p) =>
    `The restart vote passed. Restarting in ${count(p.seconds, 5)} seconds.`,
  restart_vote_rejected: () => "The restart vote was rejected.",
  restart_vote_expired: () => "The restart vote expired without passing.",
  restart_vote_abandoned: () =>
    "The restart vote was cancelled because fewer than two active players remain.",
  restart_cancelled: (p) => `The restart was cancelled because ${cancelReason(p.reason)}.`,
  game_restarted_by_vote: () => "The game was restarted by player vote.",

  hint_letter_found: (p) => {
    const times = count(p.count, 1);
    return `'${text(p.letter)}' -${count(p.cost)} pts - found ${times} time${
      times === 1 ? "" : "s"
    }!`;
  },
  hint_letter_missing: (p) =>
    `'${text(p.letter)}' -${count(p.cost)} pts - not in the prompt.`,
  guess_very_close: (p) => `"${text(p.text)}" is very close!`,
  guess_some_words_correct: () => "Some words are correct",
};

/** The words for a room-authored line, or null if this is not one. */
export function announcementText(message: ChatMessage): string | null {
  const code = message.code;
  if (!code || !(code in LINES)) return null;
  return LINES[code as AnnouncementCode](message.params ?? {});
}

/** What to show for any chat line: the room's own words, or the player's.

A player's line is their own text and is never translated - what somebody
typed is what everybody sees. */
export function chatLineText(message: ChatMessage): string {
  return announcementText(message) ?? message.text ?? "";
}
