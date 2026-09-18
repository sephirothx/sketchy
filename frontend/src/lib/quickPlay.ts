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
 * The choice is made from the lobby's live list rather than by the server, so
 * two visitors can pick the same last seat; the caller walks the candidates in
 * order and opens a room if every one of them is taken by the time it asks.
 * That costs a refused join, which the list would have to handle anyway - a
 * room fills between two pushes whatever picks it.
 */

import { DEFAULT_ALLOWED_TOOLS, DEFAULT_COLOR_MODE } from "./drawingRules.ts";
import { DEFAULT_DRAWING_SECONDS, DEFAULT_HINT_MODE } from "./roomSetup.ts";
import type {
  ColorMode,
  DrawingToolGroup,
  HintMode,
  PromptLanguage,
  RoomSummary,
  ScoringMode,
} from "../types.ts";

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
