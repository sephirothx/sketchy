/** What a lobby room row says about a room beyond its name (#581).

The wide lobby gives each public room a row of its own, with the width to say
what a player would otherwise have to open the room to find out: how long a
game will take, and which of its rules are not the usual ones. Both come from
the `RoomSummary` the room list already carries; nothing here asks the server
for more, and nothing here names a player (see `Room.to_public_roster`).

Pure, so `frontend/tests` can reach it. */

import type { RoomSummary } from "../types";
import { ui } from "../content/ui/index.ts";
import { describeDrawingRules } from "./drawingRules.ts";
import { DEFAULT_HINT_MODE, hintLabelFor } from "./roomSetup.ts";
import { promptLanguageLabel } from "./promptLanguages.ts";

/** Seconds a turn costs beyond its drawing time: choosing and results. The
    Create page's running-time estimate uses the same allowance, so the two
    never disagree about the same room. */
export const TURN_OVERHEAD_SECONDS = 24;

/** Rounded minutes for a game of `players`, never less than one. */
export function gameMinutes(
  room: Pick<RoomSummary, "rounds" | "drawingSeconds">,
  players: number,
): number {
  return Math.max(1, Math.round((players * room.rounds * (room.drawingSeconds + TURN_OVERHEAD_SECONDS)) / 60));
}

/** How long a game in this room runs: from the seats taken now - at least two,
    because a game never starts with fewer - to a full room. */
export function gameLength(
  room: Pick<RoomSummary, "rounds" | "drawingSeconds" | "playerCount" | "maxPlayers">,
): { low: number; high: number } {
  const seated = Math.min(room.maxPlayers, Math.max(2, room.playerCount));
  return { low: gameMinutes(room, seated), high: gameMinutes(room, room.maxPlayers) };
}

/** The rules this room plays by that differ from a new room's defaults, as
    short labels, in a fixed order: scoring, hints, drawing, prompts, then
    spectators. Empty for a room on standard settings, which the row says once
    rather than as six grey chips that would hide the room that is unusual. */
export function changedRoomRules(room: RoomSummary): string[] {
  const rules: string[] = [];
  if (room.scoringMode === "pressure") rules.push(ui.roomSetup.pressureScoring);
  if (room.scoringMode === "none") rules.push(ui.roomSetup.noScoring);
  if (room.hideMaskedPrompt || room.hintMode !== DEFAULT_HINT_MODE) {
    rules.push(hintLabelFor(room.hintMode, room.hideMaskedPrompt));
  }
  const drawing = describeDrawingRules(room.allowedTools, room.colorMode);
  if (drawing) rules.push(drawing);
  if (room.customPromptCount > 0) {
    rules.push(
      room.customPromptsOnly
        ? ui.inviteEntryPage.customPromptsOnly({ count: room.customPromptCount })
        : ui.inviteEntryPage.customPromptsPlusDefaults({ count: room.customPromptCount }),
    );
  }
  if (room.spectatorsSeePrompt) rules.push(ui.inviteEntryPage.spectatorsCanSeeThePrompt);
  return rules;
}

/** What the six facts are read from: a room summary, or the live room. */
export type RoomFactsInput = Pick<
  RoomSummary,
  | "playerCount" | "maxPlayers" | "rounds" | "drawingSeconds" | "scoringMode" | "hintMode"
  | "hideMaskedPrompt" | "customPromptCount" | "customPromptsOnly" | "promptListSlugs"
  | "promptLanguage" | "allowedTools" | "colorMode" | "spectatorsSeePrompt"
>;

export type RoomFactKey = "players" | "rounds" | "drawing-time" | "scoring" | "hints" | "prompts";

export interface RoomFact {
  key: RoomFactKey;
  label: string;
  value: string;
  /** Moved off a new room's default; only the three that are a choice. */
  changed: boolean;
}

/** A room's six facts (#580), in the order every place that describes a room
    draws them: the waiting room and the invite page. Scoring, hints and
    prompts are marked when the host moved them off a new room's default, so
    an unusual room reads as one before anybody joins it. */
export function roomFacts(room: RoomFactsInput): RoomFact[] {
  const slugs = room.promptListSlugs ?? [];
  const lists = slugs.length;
  // A room plays its language's Standard list unless the host chose otherwise:
  // several lists, or a single other one (a community list, a private one,
  // Extended). Either is a prompt configuration worth marking.
  const nonDefaultLists = lists > 1 || (lists === 1 && !slugs[0].endsWith("_standard"));
  const prompts = [
    promptLanguageLabel(room.promptLanguage),
    room.customPromptCount > 0
      ? room.customPromptsOnly
        ? ui.roomFacts.customOnlyShort({ count: room.customPromptCount })
        : ui.roomFacts.customShort({ count: room.customPromptCount })
      : nonDefaultLists
        ? ui.roomFacts.listsShort({ count: lists })
        : null,
  ].filter(Boolean).join(" · ");
  return [
    {
      key: "players",
      label: ui.roomPlayersPanel.players,
      value: ui.waitingRoomPanel.rosterCount({ here: room.playerCount, capacity: room.maxPlayers }),
      changed: false,
    },
    { key: "rounds", label: ui.roomSetupForm.rounds, value: String(room.rounds), changed: false },
    { key: "drawing-time", label: ui.roomSetupForm.drawingTime, value: `${room.drawingSeconds}s`, changed: false },
    {
      key: "scoring",
      label: ui.roomSetupForm.scoring,
      value: room.scoringMode === "none"
        ? ui.roomSetup.noScoring
        : room.scoringMode === "pressure" ? ui.roomSetup.pressure : ui.roomSetup.default,
      changed: room.scoringMode !== "default",
    },
    {
      key: "hints",
      label: ui.roomSetupForm.hints,
      value: hintLabelFor(room.hintMode, room.hideMaskedPrompt),
      changed: room.hideMaskedPrompt || room.hintMode !== DEFAULT_HINT_MODE,
    },
    {
      key: "prompts",
      label: ui.roomSetupForm.prompts,
      value: prompts,
      changed: room.customPromptCount > 0 || nonDefaultLists,
    },
  ];
}

/** What else the host changed, beyond the six: said once, under them, and
    only when there is something. */
export function otherRoomRules(room: RoomFactsInput): string[] {
  return [
    describeDrawingRules(room.allowedTools, room.colorMode),
    room.spectatorsSeePrompt ? ui.roomFacts.spectatorsSeeThePrompt : null,
  ].filter((rule): rule is string => Boolean(rule));
}
