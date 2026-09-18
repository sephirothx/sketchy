/**
 * Quick play (#589): one press from the lobby to a room.
 *
 * The name field names you and nothing else, so this is the control that
 * plays. It joins a public room that is **waiting** for players with a seat
 * free, and opens one on the standard rules when there is none - which is what
 * makes it worth pressing on an empty instance, and what makes the room it
 * opens the one the next visitor's Quick play finds.
 *
 * It only joins a room in the player's prompt language, and never a game
 * already under way. Landing mid-round with no prompt
 * and half a drawing on screen is a worse first minute than waiting in a room
 * with the scratch pad (#591), and the room's own card is still there for
 * anybody who wants to watch.
 *
 * The choice is made from the lobby's live list, which is a moment old: a room
 * can fill, start or go private between the push and the press. So the join
 * says it is a Quick play one and the server re-checks, at the instant it
 * adds the seat, that the room is still public and waiting (`room_not_open`
 * when it is not). The caller walks the candidates in order and opens a room
 * only when every one of them turned out to be gone - and stops at the first
 * refusal that is about the player rather than the room, which the next room
 * would give too.
 */

import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "./drawingRules.ts";
import type { RoomsState } from "./lobbyRooms.ts";
import { DEFAULT_DRAWING_SECONDS, DEFAULT_HINT_MODE } from "./roomSetup.ts";
import type {
  AckResponse,
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PromptLanguage,
  RoomSummary,
  ScoringMode,
} from "../types.ts";

/**
 * Whether the list is one Quick play can decide from. Before the first
 * snapshot the list is empty because nothing has arrived, not because nothing
 * is open - and deciding from that opens a room beside the ones waiting. A
 * stale or resyncing list is the same kind of not-yet.
 */
export function quickPlayReady(state: RoomsState): boolean {
  return state.loaded && !state.stale && !state.needsResync;
}

/**
 * The refusals that are about one room only: it filled, it went, or it is no
 * longer public and waiting. Anything else - joining too fast, the database
 * busy, a name somebody took, the server draining - the next room would say
 * too, so it is shown rather than walked past into opening a room.
 */
export const QUICK_PLAY_SKIPS: ReadonlySet<string> = new Set([
  "room_full",
  "room_not_found",
  "room_ended",
  "room_not_open",
]);

/**
 * Walk the candidates and settle on one answer: the first seat, the first
 * refusal that is about the player rather than a room (the next room would
 * say it too), or - when every candidate turned out to be gone - the room
 * `open` makes. `join` and `open` are the two socket requests; they are
 * parameters so the walk can be tested without a server.
 */
export async function runQuickPlay<Room>(
  candidates: readonly Room[],
  join: (room: Room) => Promise<AckResponse>,
  open: () => Promise<AckResponse>,
): Promise<AckResponse> {
  for (const room of candidates) {
    const answer = await join(room);
    if (answer.ok || !QUICK_PLAY_SKIPS.has(answer.errorCode ?? "")) return answer;
  }
  return open();
}

/**
 * The rooms Quick play would try, best first: only rooms whose words are in
 * your prompt language, and the fullest before the emptier, because the room
 * one seat short of a game is the one worth filling.
 *
 * Only your language, not yours first: a room in another language would hand
 * you words you cannot draw or guess, and one press is not the place to
 * accept that. The lobby's list still shows every room, yours first
 * (R-PROMPT-11), for anybody who wants to choose one on purpose.
 */
export function quickPlayCandidates(
  rooms: readonly RoomSummary[],
  language: PromptLanguage,
): RoomSummary[] {
  return rooms
    .filter(
      (room) =>
        room.isPublic
        && room.state === "waiting"
        && room.playerCount < room.maxPlayers
        && room.promptLanguage === language,
    )
    .sort((a, b) => b.playerCount - a.playerCount);
}

export interface QuickPlayRoom {
  name: string;
  isPublic: boolean;
  maxPlayers: number;
  rounds: number;
  drawingSeconds: number;
  hintMode: HintMode;
  scoringMode: ScoringMode;
  spectatorsSeePrompt: boolean;
  hideMaskedPrompt: boolean;
  allowedTools: DrawingToolGroup[];
  colorMode: ColorMode;
  promptLanguage: PromptLanguage;
  promptListSlugs: string[];
  customPrompts: string;
  customPromptsOnly: boolean;
}

/**
 * The room Quick play opens when nothing is waiting: the create form's own
 * defaults, in the player's language, and **public** - a private one would
 * leave the next visitor's Quick play with nothing to find again.
 *
 * The name is left to the server, which gives a room one of its own.
 */
export function quickPlayRoom(
  promptLanguage: PromptLanguage,
  colorblindSafeColors: boolean,
): QuickPlayRoom {
  return {
    name: "",
    isPublic: true,
    maxPlayers: 8,
    rounds: 3,
    drawingSeconds: DEFAULT_DRAWING_SECONDS,
    hintMode: DEFAULT_HINT_MODE,
    scoringMode: "default",
    spectatorsSeePrompt: false,
    hideMaskedPrompt: false,
    allowedTools: DEFAULT_ALLOWED_TOOLS,
    colorMode: colorblindSafeColors ? "colorblind_safe" : DEFAULT_COLOR_MODE,
    promptLanguage,
    // Empty on purpose: the server fills it with the declared language's
    // Standard list (payloads.py), which saves fetching the catalogue to
    // press one button.
    promptListSlugs: [],
    customPrompts: "",
    customPromptsOnly: false,
  };
}
