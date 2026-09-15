/** Where each server and connection notice is shown: a banner, a room chip, or nowhere. */

import type { ConnectionStatus } from "./connectionStatus.ts";

export type BannerNotice =
  | "update-required"
  | "server-full"
  | "paused"
  | "drain"
  | "restarted"
  | "connection";

export type ChipNotice = "drain" | "connection";

export interface NoticeFacts {
  inRoom: boolean;
  updateRequired: boolean;
  serverFull: boolean;
  paused: boolean;
  draining: boolean;
  restarted: boolean;
  connection: ConnectionStatus;
}

export interface NoticePlacement {
  /** Top-of-page banners, in the order they stack. */
  banners: BannerNotice[];
  /** Chips in the room header, in the order they sit. */
  chips: ChipNotice[];
}

/**
 * Decide where every notice goes (#797).
 *
 * A room lays itself out to the viewport (R-UX-01), so a banner there takes its
 * height straight off the canvas and, before the banner stack reserved its
 * space, sat on top of the room's header and took its taps. The two notices
 * that actually happen mid-game - a planned-deploy drain and a dropped
 * connection - are therefore chips in the header instead, with the full
 * sentence a tap away (R-UX-07).
 *
 * The rest stay banners, and each for a reason. **Update required** means the
 * tab can no longer play at all: nothing underneath it works, and the one thing
 * left to offer is the Reload on the banner. **Server full** and **restarted**
 * belong outside a room - turned away at the handshake, or back after the room
 * was lost, which a room says with its own end screen instead - so a chip would
 * never be the right home for either. **Paused** stops new rooms only; a game already running carries on,
 * so a player in a room is not told about it at all.
 *
 * A drain supersedes the pause, as it always has: the server is going away,
 * which is the more urgent of the two. An update-required tab has stopped
 * reconnecting on purpose, so the connection notice would only contradict the
 * banner that explains why.
 */
export function placeNotices(facts: NoticeFacts): NoticePlacement {
  const banners: BannerNotice[] = [];
  const chips: ChipNotice[] = [];
  const connectionTrouble = facts.connection !== "connected" && !facts.updateRequired;

  if (facts.updateRequired) banners.push("update-required");
  if (facts.serverFull && !facts.updateRequired) banners.push("server-full");
  if (facts.paused && !facts.draining && !facts.inRoom) banners.push("paused");
  if (facts.draining) (facts.inRoom ? chips : banners).push("drain");
  // Inside a room the end screen says it (roomStage), and says it better.
  if (facts.restarted && !facts.inRoom) banners.push("restarted");
  if (connectionTrouble) (facts.inRoom ? chips : banners).push("connection");

  return { banners, chips };
}

export type RoomPauseCause = "reconnecting" | "offline" | "server-update" | "failed";

export type RoomStage =
  | { kind: "live" }
  | { kind: "paused"; cause: RoomPauseCause }
  | { kind: "ended"; reason: "server-update" | "room-closed" };

export interface RoomStageFacts {
  /** The room this tab is showing. */
  code: string | null;
  connection: ConnectionStatus;
  pauseDue: boolean;
  lostDuringDrain: boolean;
  updateRequired: boolean;
  roomEnded: { code: string; reason: "server-update" | "room-closed" } | null;
}

/**
 * What the room's stage - players, canvas, chat, the guess field - should be (#823).
 *
 * A header chip was the only sign of an outage, and the room went on looking
 * alive underneath it: the ring kept counting, the guess field and the brush
 * kept taking input that was going nowhere. And once the server came back
 * without the room, the player was left on that room for good, told to reload
 * a page that could not bring it back.
 *
 * So trouble that outlasts the pause delay **pauses** the stage: it is dimmed
 * and inert, the ring stops, and a card says why. The header stays usable,
 * because Leave and the menu are how somebody gets out of a room that is not
 * coming back. A room the server says no longer exists is **ended**: the stage
 * is replaced by a card that says so and why, and offers the lobby.
 *
 * An out-of-date tab is left alone - its banner is the explanation, and the
 * socket it has stopped reopening would otherwise pause the room for ever.
 */
export function roomStage(facts: RoomStageFacts): RoomStage {
  if (facts.roomEnded && facts.code !== null && facts.roomEnded.code === facts.code) {
    return { kind: "ended", reason: facts.roomEnded.reason };
  }
  if (facts.updateRequired || facts.connection === "connected" || !facts.pauseDue) {
    return { kind: "live" };
  }
  if (facts.connection === "failed") return { kind: "paused", cause: "failed" };
  if (facts.lostDuringDrain) return { kind: "paused", cause: "server-update" };
  return { kind: "paused", cause: facts.connection };
}

/** How long the drain's opening card stays before it folds into the header chip. */
export const DRAIN_CUE_MS = 5000;
/** The drain's last stretch, when the chip turns red and the stage says so too. */
export const DRAIN_FINAL_SECONDS = 10;

export interface DrainCueFacts {
  /** Identifies this drain; a new one is a new cue. */
  drainStartedAt: string | null;
  /** The drain whose opening card was already shown. */
  cueSeenFor: string | null;
  secondsLeft: number;
  /** A game is being played, so there is a game for the drain to end. */
  playing: boolean;
}

/**
 * How loudly a drain is said on a live room stage (#826).
 *
 * The header chip alone was too easy to miss: it turns up beside the round
 * while somebody is drawing or typing a guess, and the game ending under them
 * is the one notice worth breaking their attention for. So the drain **opens**
 * with a card over the stage, once per drain, which folds into the chip after
 * `DRAIN_CUE_MS` or a tap - costing no canvas for the rest of the window. Its
 * **last seconds** are said again, by a line that does not cover the canvas or
 * take a tap, so a guess can still be finished.
 *
 * Only on a live stage: a paused or ended stage already has its own card.
 */
export function drainCue(facts: DrainCueFacts): { card: boolean; finalCountdown: boolean } {
  if (facts.drainStartedAt === null) return { card: false, finalCountdown: false };
  const card = facts.cueSeenFor !== facts.drainStartedAt;
  const finalCountdown =
    !card && facts.playing && facts.secondsLeft > 0 && facts.secondsLeft <= DRAIN_FINAL_SECONDS;
  return { card, finalCountdown };
}
