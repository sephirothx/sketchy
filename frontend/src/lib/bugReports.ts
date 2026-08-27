/** Filing a bug, and reading the queue of filed ones.

Two halves that must not be confused. `clientContext` is what the reporter's
browser said about itself - useful, and evidence supplied by a player. The
server adds its own account of their seat, which is the only half a reader may
treat as fact. Both come back on the queue payload, labelled. */

import { apiRequest } from "./api.ts";
import { recentClientErrors, type ClientErrorEntry } from "./clientErrorLog.ts";
import { connectionTelemetry } from "./socket.ts";

export type BugReportArea =
  | "drawing_and_canvas"
  | "guessing_and_chat"
  | "rounds_and_scoring"
  | "rooms_and_lobby"
  | "prompt_lists"
  | "account_and_settings"
  | "connection_and_sync"
  | "performance"
  | "accessibility"
  | "other";

export type BugReportSeverity = "blocks_play" | "major" | "minor";
export type BugReportStatus = "pending" | "resolved" | "dismissed";
export type ScreenshotStatus = "none" | "ready" | "erased";

/** Offered in this order: where a player thinks they were, in the words they
    would use, ending in the honest escape hatch. */
export const BUG_AREAS: { value: BugReportArea; label: string }[] = [
  { value: "drawing_and_canvas", label: "Drawing and canvas" },
  { value: "guessing_and_chat", label: "Guessing and chat" },
  { value: "rounds_and_scoring", label: "Rounds, scoring and results" },
  { value: "rooms_and_lobby", label: "Rooms and lobby" },
  { value: "prompt_lists", label: "Prompt lists" },
  { value: "account_and_settings", label: "Account and settings" },
  { value: "connection_and_sync", label: "Connection and sync" },
  { value: "performance", label: "Performance" },
  { value: "accessibility", label: "Accessibility" },
  { value: "other", label: "Something else" },
];

/** Three, because a fourth would be a priority scheme and this is a question
    the reporter can actually answer about their own experience. */
export const BUG_SEVERITIES: { value: BugReportSeverity; label: string }[] = [
  { value: "blocks_play", label: "Blocks play — I could not carry on" },
  { value: "major", label: "Major — hard to play around" },
  { value: "minor", label: "Minor — worth fixing one day" },
];

export interface BugReportScreenshot {
  status: ScreenshotStatus;
  contentType: string | null;
  byteSize: number | null;
  width: number | null;
  height: number | null;
  checksum: string | null;
}

export interface BugReportReporter {
  displayName: string;
  registered: boolean;
  createdAt: string;
}

export interface BugReport {
  id: string;
  reporterUserId: string | null;
  /** Null when the account is gone; the report outlives it. */
  reporter: BugReportReporter | null;
  area: BugReportArea;
  severity: BugReportSeverity;
  summary: string;
  details: string;
  buildSha: string | null;
  route: string | null;
  roomCode: string | null;
  gameId: string | null;
  turnId: string | null;
  /** Reporter-supplied. Shaped by `collectClientContext`, but never trusted. */
  clientContext: Record<string, unknown>;
  /** What the server itself knew about their seat when they filed. */
  serverContext: Record<string, unknown>;
  screenshot: BugReportScreenshot;
  status: BugReportStatus;
  reviewedByUserId: string | null;
  resolutionNote: string | null;
  createdAt: string;
  updatedAt: string;
  reviewedAt: string | null;
}

export interface CollectedContext extends Record<string, unknown> {
  buildSha: string;
  route: string;
  clientTime: string;
  recentErrors: ClientErrorEntry[];
}

type NetworkInformation = {
  effectiveType?: string;
  downlink?: number;
  rtt?: number;
  saveData?: boolean;
};

function mediaQuery(query: string): boolean | null {
  if (typeof window.matchMedia !== "function") return null;
  return window.matchMedia(query).matches;
}

/** Everything about this tab worth knowing before reproducing a bug.
 *
 * Gathered generously on purpose: the reporter gets one shot at describing it,
 * and the difference between a report that can be acted on and one that cannot
 * is usually a detail nobody thought to ask for. What is deliberately absent is
 * anything private - the query string, chat text, and above all the prompt in
 * play, which a guesser filing a bug must not be handed back.
 *
 * Sources are parameters so a test can supply them; every one is optional
 * because this must never be the thing that fails while somebody reports a
 * failure.
 */
export function collectClientContext(sources: {
  roomCode?: string | null;
  roomState?: string | null;
  phase?: string | null;
  roundNumber?: number | null;
  totalRounds?: number | null;
  playerCount?: number | null;
  isDrawer?: boolean | null;
  settings?: Record<string, unknown> | null;
  canvasBudget?: { fill: boolean; stroke: boolean } | null;
  screenshot?: { width: number; height: number; byteSize: number } | null;
} = {}): CollectedContext {
  const connection = connectionTelemetry();
  const network = (navigator as Navigator & { connection?: NetworkInformation }).connection;
  const memory = (performance as Performance & {
    memory?: { usedJSHeapSize: number; jsHeapSizeLimit: number };
  }).memory;

  return {
    buildSha: __APP_COMMIT_SHA__,
    commitDate: __APP_COMMIT_DATE__,
    buildTime: __APP_BUILD_TIME__,
    // Path only. A query string is where identifiers and invite codes live,
    // and none of that belongs in a report.
    route: window.location.pathname,
    clientTime: new Date().toISOString(),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,

    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      dpr: window.devicePixelRatio,
      screenWidth: window.screen?.width ?? null,
      screenHeight: window.screen?.height ?? null,
      orientation: window.screen?.orientation?.type ?? null,
    },
    browser: {
      userAgent: navigator.userAgent,
      language: navigator.language,
      platform: (navigator as Navigator & { platform?: string }).platform ?? null,
      hardwareConcurrency: navigator.hardwareConcurrency ?? null,
      deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? null,
      maxTouchPoints: navigator.maxTouchPoints ?? null,
      cookieEnabled: navigator.cookieEnabled,
    },
    // A bug that only happens with reduced motion, forced colors or a
    // particular theme is a bug that is invisible without these three lines.
    preferences: {
      prefersReducedMotion: mediaQuery("(prefers-reduced-motion: reduce)"),
      prefersColorScheme: mediaQuery("(prefers-color-scheme: dark)") ? "dark" : "light",
      forcedColors: mediaQuery("(forced-colors: active)"),
      pointerCoarse: mediaQuery("(pointer: coarse)"),
      settings: sources.settings ?? null,
    },
    connection: {
      online: navigator.onLine,
      ...connection,
      effectiveType: network?.effectiveType ?? null,
      downlinkMbps: network?.downlink ?? null,
      rttMs: network?.rtt ?? null,
      saveData: network?.saveData ?? null,
    },
    performance: {
      // Time on the page is the difference between "it broke immediately" and
      // "it broke after an hour", which are rarely the same bug.
      uptimeMs: Math.round(performance.now()),
      usedJsHeapMb: memory ? Math.round(memory.usedJSHeapSize / 1048576) : null,
      jsHeapLimitMb: memory ? Math.round(memory.jsHeapSizeLimit / 1048576) : null,
    },
    // The room as the client believes it to be. The server overwrites its own
    // account of this from live state; the two disagreeing is itself a finding.
    room: {
      code: sources.roomCode ?? null,
      state: sources.roomState ?? null,
      phase: sources.phase ?? null,
      roundNumber: sources.roundNumber ?? null,
      totalRounds: sources.totalRounds ?? null,
      playerCount: sources.playerCount ?? null,
      isDrawer: sources.isDrawer ?? null,
      canvasFillAvailable: sources.canvasBudget?.fill ?? null,
      canvasStrokeAvailable: sources.canvasBudget?.stroke ?? null,
    },
    screenshotWidth: sources.screenshot?.width ?? null,
    screenshotHeight: sources.screenshot?.height ?? null,
    recentErrors: recentClientErrors(),
  };
}

export function submitBugReport(input: {
  area: BugReportArea;
  severity: BugReportSeverity;
  summary: string;
  details: string;
  clientContext?: Record<string, unknown>;
  roomCode?: string | null;
  screenshot?: string | null;
}): Promise<{ id: string; status: BugReportStatus; createdAt: string }> {
  return apiRequest("/api/bug-reports", {
    method: "POST",
    body: input,
    // A screenshot makes this a much larger body than the JSON default allows
    // time for on a slow uplink.
    timeoutMs: 20000,
  });
}

export function listBugReports(status?: BugReportStatus): Promise<{ reports: BugReport[] }> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest(`/api/admin/bug-reports${query}`);
}

export function reviewBugReport(
  reportId: string,
  status: Exclude<BugReportStatus, "pending">,
  note: string,
): Promise<BugReport> {
  return apiRequest(`/api/admin/bug-reports/${reportId}`, {
    method: "PATCH",
    body: { status, note },
  });
}

/** Put `text` on the clipboard, by whichever route this browser allows.
 *
 * The async Clipboard API is the right one and is refused often enough to
 * matter - an insecure origin, a missing permission, or a click the browser did
 * not count as user activation. Falling back to the old selection-and-copy path
 * keeps a triage tool working in the places an operator actually opens it,
 * rather than telling them their browser said no.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fall through to the legacy path rather than giving up here.
  }
  try {
    const carrier = document.createElement("textarea");
    carrier.value = text;
    // Off-screen but still focusable: a `display: none` element cannot be
    // selected, and an unselected one copies nothing.
    carrier.setAttribute("readonly", "");
    carrier.style.position = "fixed";
    carrier.style.top = "-1000px";
    document.body.appendChild(carrier);
    carrier.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(carrier);
    return copied;
  } catch {
    return false;
  }
}

export function bugReportScreenshotUrl(reportId: string): string {
  return `/api/admin/bug-reports/${reportId}/screenshot`;
}

/** How a room reads in a diagnostics row.
 *
 * The round is appended only when there really is one. Both counters default to
 * zero before a game starts, and "round 0 of 0" reads as gameplay state rather
 * than as the absence of it - misleading exactly the reader who is trying to
 * work out what the player was doing.
 */
export function roomSummary(
  code: string | null | undefined,
  round: number | null | undefined,
  total: number | null | undefined,
): string {
  if (!code) return "Not in a room";
  if (!round || !total || round < 1 || total < 1) return `${code} · not in a round`;
  return `${code} · round ${round} of ${total}`;
}

export function humanizeBugValue(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/* ------------------------------------------------------------------ triage */

function flatten(value: unknown, prefix: string, into: string[]): void {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) {
    if (value.length) into.push(`${prefix}: ${JSON.stringify(value)}`);
    return;
  }
  if (typeof value === "object") {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, into);
    }
    return;
  }
  into.push(`${prefix}: ${String(value)}`);
}

/** The whole report as one block of Markdown, for a clipboard.
 *
 * Deliberately flat and deterministic: stable headings, one fact per line, ids
 * written out in full, nothing abbreviated for display. It has to survive being
 * pasted into an issue by a person and being read by a model asked to reproduce
 * the bug, and those want the same thing - no prose glue between the facts.
 *
 * Pure so that the format itself can be tested, which is the only way a format
 * anyone depends on stays stable.
 */
export function bugReportTriageText(report: BugReport): string {
  const lines: string[] = [
    `# Sketchy bug report ${report.id}`,
    `status: ${report.status}`,
    `filed: ${report.createdAt}`,
    `reporter: ${
      report.reporter
        ? `${report.reporter.registered ? "registered" : "guest"} account, created ${report.reporter.createdAt}`
        : "account since deleted"
    }`,
    `area: ${report.area}`,
    `severity: ${report.severity}`,
    "",
    "## Summary",
    report.summary,
    "",
    "## Details",
    report.details,
    "",
    "## Environment",
    `build: ${report.buildSha ?? "unknown"}`,
    `route: ${report.route ?? "unknown"}`,
  ];

  if (report.roomCode) lines.push(`room: ${report.roomCode}`);
  if (report.gameId) lines.push(`game_id: ${report.gameId}`);
  if (report.turnId) lines.push(`turn_id: ${report.turnId}`);

  const client: string[] = [];
  for (const [key, value] of Object.entries(report.clientContext)) {
    if (key === "recentErrors") continue;
    flatten(value, key, client);
  }
  if (client.length) {
    lines.push("", "### Reported by the client", ...client.sort());
  }

  const server: string[] = [];
  flatten(report.serverContext, "", server);
  if (server.length) {
    lines.push("", "### Observed by the server", ...server.sort());
  }

  const errors = report.clientContext.recentErrors;
  if (Array.isArray(errors) && errors.length) {
    // Newest first: the last thing to go wrong is the thing to read first.
    const newestFirst = [...errors].reverse() as ClientErrorEntry[];
    lines.push("", `## Client errors (${newestFirst.length}, newest first)`);
    newestFirst.forEach((entry, index) => {
      lines.push(`${index + 1}. ${entry.at} ${entry.kind} ${entry.message}`);
    });
  }

  lines.push("", "## Screenshot");
  if (report.screenshot.status === "ready") {
    lines.push(
      `attached: ${report.screenshot.width ?? "?"}x${report.screenshot.height ?? "?"} `
      + `${report.screenshot.contentType ?? "image"} ${report.screenshot.byteSize ?? 0} bytes`,
      `url: ${bugReportScreenshotUrl(report.id)}`,
      `sha256: ${report.screenshot.checksum ?? "unknown"}`,
    );
  } else if (report.screenshot.status === "erased") {
    lines.push("erased when the report was decided");
  } else {
    lines.push("none");
  }

  if (report.resolutionNote) {
    lines.push("", "## Resolution", `decided: ${report.reviewedAt}`, report.resolutionNote);
  }

  return lines.join("\n");
}
