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
 * are only ever raised outside a room - turned away at the handshake, or
 * back after the room was lost - so a chip would never be the right home for
 * either. **Paused** stops new rooms only; a game already running carries on,
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
  if (facts.restarted) banners.push("restarted");
  if (connectionTrouble) (facts.inRoom ? chips : banners).push("connection");

  return { banners, chips };
}
