/** The administrator surfaces that change something.

Everything in `operations.ts` beside this is a read. These are the first
writes: tuning a runtime value, pausing new rooms, ending somebody's room,
granting a role. Kept in their own module for the same reason the panel keeps
them in their own tab — a call that closes a room should not be one import away
from a call that draws a chart. */

import { apiRequest } from "./api.ts";

/** One runtime value, described well enough to build a control for it.

The server sends the bounds, the unit and the sentence explaining the
trade-off, so the page needs to know nothing about any particular setting and
adding one does not mean editing this file. */
export interface Tunable {
  name: string;
  value: number;
  /** What this build compiles in. */
  default: number;
  /** What this process started at — the default, or the environment's answer. */
  bootValue: number;
  minimum: number;
  maximum: number;
  unit: string;
  /** Whether the value space is whole numbers, so a control can match it. */
  integral: boolean;
  audience: "server" | "client";
  description: string;
  /** The variable that supplied the boot value, when one did. */
  envVar: string | null;
  source: "default" | "environment" | "stored";
  /** A stored row this release refuses; `value` is what is actually running. */
  overrideRejected: boolean;
}

export interface LiveSeat {
  id: string;
  nickname: string;
  isSpectator: boolean;
  connected: boolean;
}

export interface LiveRoom {
  id: string;
  code: string;
  name: string;
  isPublic: boolean;
  state: string;
  phase: string | null;
  roundNumber: number | null;
  players: number;
  spectators: number;
  connected: number;
  seats: LiveSeat[];
}

export interface MaintenanceState {
  paused: boolean;
  draining: boolean;
  readiness: string;
  /** What a shutdown started now would give live games to finish. */
  drainSeconds: number;
}

export function readTunables(): Promise<{ tunables: Tunable[] }> {
  return apiRequest("/api/admin/tunables");
}

/** Change and reset settings in one request.

One request rather than several because the server validates them as a set: a
pair that only makes sense together — a faster client cadence and the larger
budget that admits it — is refused when the two arrive separately. */
export function changeTunables(changes: {
  values?: Record<string, number>;
  reset?: string[];
}): Promise<{ tunables: Tunable[] }> {
  return apiRequest("/api/admin/tunables", { method: "PATCH", body: changes });
}

export function readMaintenance(): Promise<MaintenanceState> {
  return apiRequest("/api/admin/maintenance");
}

export function setMaintenance(
  paused: boolean,
  reason: string,
): Promise<MaintenanceState> {
  return apiRequest("/api/admin/maintenance", {
    method: "POST",
    body: { paused, reason },
  });
}

/** Stop the server, draining live games for `drainSeconds` first.

Omit `drainSeconds` to use whatever the drain window is currently set to. A
value here applies to this shutdown only; it does not change the setting. */
export function initiateShutdown(
  reason: string,
  drainSeconds?: number,
): Promise<{ draining: boolean; drainSeconds: number }> {
  return apiRequest("/api/admin/shutdown", {
    method: "POST",
    body: drainSeconds === undefined ? { reason } : { reason, drainSeconds },
  });
}

export function readLiveRooms(): Promise<{ rooms: LiveRoom[] }> {
  return apiRequest("/api/admin/rooms");
}

export function closeRoom(roomId: string): Promise<{ closed: string }> {
  return apiRequest(`/api/admin/rooms/${roomId}`, { method: "DELETE" });
}

export function kickPlayer(
  roomId: string,
  playerId: string,
): Promise<{ kicked: string }> {
  return apiRequest(`/api/admin/rooms/${roomId}/players/${playerId}`, {
    method: "DELETE",
  });
}

export function endTurn(roomId: string): Promise<{ endedTurnIn: string }> {
  return apiRequest(`/api/admin/rooms/${roomId}/end-turn`, { method: "POST" });
}

export function setPlayerRole(
  userId: string,
  role: "user" | "moderator",
  reason: string,
): Promise<{ id: string; role: string }> {
  return apiRequest(`/api/admin/players/${userId}/role`, {
    method: "PATCH",
    body: { role, reason },
  });
}

/** How the server describes its own admission state, for the overview banner.

Pulled out of the page because it is the one thing on that banner that can be
wrong in a way nobody notices: it read "accepting rooms" unconditionally, which
is the opposite of the truth during a pause or a drain. A pure function is
something a test can hold still. */
export function admissionLabel(
  maintenance: Pick<MaintenanceState, "paused" | "draining"> | null,
): string {
  if (maintenance?.draining) return "draining — no new rooms";
  if (maintenance?.paused) return "paused — no new rooms";
  return "accepting rooms";
}

/** Whether the server is taking new rooms, for the banner's tone and heading. */
export function isAdmitting(
  maintenance: Pick<MaintenanceState, "paused" | "draining"> | null,
): boolean {
  return admissionLabel(maintenance) === "accepting rooms";
}

/** Whether the shutdown control should refuse the click it is about to get.

Both steps of the confirm ask this, not just the first: the fields stay
editable while the confirm is showing, and a drain can begin in between —
another operator, or a stop from the host — so a second step guarded only by
"a request is in flight" is a button whose one job is to be refused. */
export function shutdownBlocked({
  busy,
  maintenance,
  reason,
}: {
  busy: boolean;
  maintenance: Pick<MaintenanceState, "draining"> | null;
  reason: string;
}): boolean {
  return busy || Boolean(maintenance?.draining) || reason.trim().length < 3;
}

/** The subsystem a setting belongs to, taken from its name.

The server namespaces every tunable (`budget.drawing`, `rooms.socket_limit`),
so the grouping is already in the data and this page does not need a list of
settings it would have to be kept in step with. */
export function tunableGroup(name: string): string {
  return name.includes(".") ? name.slice(0, name.indexOf(".")) : "other";
}

const GROUP_LABELS: Record<string, string> = {
  budget: "Command budgets",
  rooms: "Room and connection ceilings",
  turn: "Turn timing",
  restart: "Restart votes",
  shutdown: "Planned shutdown",
  client: "Client cadences",
};

export function groupLabel(group: string): string {
  return GROUP_LABELS[group] ?? group;
}

/** The settings in force, grouped for display, in the order the server sent. */
export function groupTunables(tunables: Tunable[]): [string, Tunable[]][] {
  const groups = new Map<string, Tunable[]>();
  for (const tunable of tunables) {
    const key = tunableGroup(tunable.name);
    const existing = groups.get(key);
    if (existing) existing.push(tunable);
    else groups.set(key, [tunable]);
  }
  return [...groups.entries()];
}

/** The part of the name that is not the group, for a per-setting label. */
export function tunableLabel(name: string): string {
  const tail = name.includes(".") ? name.slice(name.indexOf(".") + 1) : name;
  return tail.replace(/_/g, " ");
}
