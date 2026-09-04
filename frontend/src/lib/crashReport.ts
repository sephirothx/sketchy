/** What the crash page pre-fills into a bug report, and the scrub it gets first.

A player looking at a crash page has one useful thing to add - what they were
doing - and everything else is already known: the error, where in the tree it
was thrown, which page. So the report is written before they are asked, and
their words go on top. That also means the report is filled by code rather than
by a person choosing what to paste, and code has to be told what not to say:
the same things the server's logs refuse to print (`logging_config.py`), plus a
query string, which is where invite codes and identifiers live (R-BUG-06).

Pure, so the budget arithmetic and the redaction can be tested where there is no
browser. */

import type { BugReportArea, BugReportSeverity } from "./bugReports.ts";

/** Which boundary caught it: the one around the whole app, or the live room. */
export type CrashScope = "app" | "room";

/** The server's limits (`MAX_SUMMARY`, `MAX_DETAILS` in `api/bug_reports.py`). */
export const MAX_SUMMARY_CHARS = 200;
export const MAX_DETAILS_CHARS = 4000;
/** The diagnostic never takes more than this of the details, so the player
    always has room to write. */
export const MAX_DIAGNOSTIC_CHARS = 2500;
const MAX_STACK_FRAMES = 8;
const MAX_TREE_FRAMES = 12;

export const DIAGNOSTIC_DIVIDER = "--- Diagnostic ---";

/* The first four mirror `_REDACTIONS` in backend/app/logging_config.py, in the
   same order and for the same reason: a bearer token inside a URL must be
   hidden as a token, not left because the URL rule saw no password. The last
   is this side's own - a query string on anything shaped like a URL or path. */
const REDACTIONS: readonly [RegExp, string][] = [
  [/\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+/gi, "$1 ***"],
  [
    /\b(password|passwd|pwd|secret|token|api[_-]?key|[a-z_]*session|cookie)(\s*[:=]\s*)([^\s;,&"']+)/gi,
    "$1$2***",
  ],
  [/:\/\/([^:/@\s]+):([^@\s]+)@/g, "://$1:***@"],
  [/[\w.+-]+@((?:[\w-]+\.)+[\w-]{2,})/g, "***@$1"],
  [/((?:https?:\/\/|\/)[^\s?#"'()]*)\?[^\s"'()#]*/g, "$1?***"],
];

export function redactDiagnostic(text: string): string {
  return REDACTIONS.reduce(
    (out, [pattern, replacement]) => out.replace(pattern, replacement),
    text,
  );
}

/** Path only, like `collectClientContext` sends and `_safe_route` stores. */
function pathOnly(route: string): string {
  const cut = route.search(/[?#]/);
  return cut === -1 ? route : route.slice(0, cut);
}

/** The area a triager would file this under, guessed from where it happened.
    One of the ten that exist (R-BUG-03): a crash is not a new kind of bug, it
    is a bug in one of the areas that has stopped the page. */
export function crashArea(scope: CrashScope, route: string, phase: string | null): BugReportArea {
  if (scope === "room") {
    return phase === "drawing" ? "drawing_and_canvas" : "rooms_and_lobby";
  }
  const path = pathOnly(route);
  if (path === "/" || path === "/create" || path.startsWith("/room/")) return "rooms_and_lobby";
  if (path.startsWith("/prompt-lists") || path.startsWith("/my-prompt-lists")) return "prompt_lists";
  if (
    path.startsWith("/profile")
    || path.startsWith("/settings")
    || path === "/forgot-password"
    || path === "/reset-password"
    || path === "/verify-email"
  ) {
    return "account_and_settings";
  }
  return "other";
}

function describeError(error: unknown): { name: string; message: string; frames: string[] } {
  if (error instanceof Error) {
    // Chrome's stack opens with the message line; Firefox's does not. Drop
    // whatever repeats the error and keep the frames.
    const frames = (error.stack ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter((line, index) => line && !(index === 0 && line.startsWith(error.name)))
      .slice(0, MAX_STACK_FRAMES);
    return { name: error.name || "Error", message: error.message, frames };
  }
  let message: string;
  try {
    message = typeof error === "string" ? error : JSON.stringify(error) ?? String(error);
  } catch {
    message = String(error);
  }
  return { name: "Thrown value", message, frames: [] };
}

export interface CrashPrefill {
  area: BugReportArea;
  severity: BugReportSeverity;
  summary: string;
  /** Already redacted. Goes under the player's words in `details`. */
  diagnosticBlock: string;
}

export function prefillCrashReport(input: {
  scope: CrashScope;
  route: string;
  error: unknown;
  componentStack: string | null;
  phase?: string | null;
}): CrashPrefill {
  const { name, message, frames } = describeError(input.error);
  const route = pathOnly(input.route);
  const summary = redactDiagnostic(`Crash on ${route}: ${name}: ${message}`)
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_SUMMARY_CHARS);

  const tree = (input.componentStack ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, MAX_TREE_FRAMES);

  const lines = [
    `Scope: ${input.scope === "room" ? "live room" : "application root"}`,
    `Page: ${route}`,
    `Error: ${name}: ${message}`,
  ];
  if (frames.length) lines.push("Stack:", ...frames.map((frame) => `  ${frame}`));
  if (tree.length) lines.push("Component tree:", ...tree.map((frame) => `  ${frame}`));

  return {
    area: crashArea(input.scope, route, input.phase ?? null),
    // The screen is gone; there is no playing around that.
    severity: "blocks_play",
    summary,
    diagnosticBlock: redactDiagnostic(lines.join("\n")).slice(0, MAX_DIAGNOSTIC_CHARS),
  };
}

/** How many characters the player may write once the diagnostic has its share. */
export function playerTextBudget(diagnosticBlock: string): number {
  if (!diagnosticBlock) return MAX_DETAILS_CHARS;
  // The blank line before the divider, the divider, and the newline after it.
  return Math.max(0, MAX_DETAILS_CHARS - diagnosticBlock.length - DIAGNOSTIC_DIVIDER.length - 3);
}

/** The `details` field: the player's words first, the diagnostic under a
    divider, and never more than the server accepts. The player's text is cut
    to its budget rather than the diagnostic being cut from the end, because
    the end of the diagnostic is the component tree - the part that says where. */
export function composeDetails(playerText: string, diagnosticBlock: string): string {
  const text = playerText.trim().slice(0, playerTextBudget(diagnosticBlock));
  const parts: string[] = [];
  if (text) parts.push(text);
  if (diagnosticBlock) parts.push(`${DIAGNOSTIC_DIVIDER}\n${diagnosticBlock}`);
  return parts.join("\n\n").slice(0, MAX_DETAILS_CHARS);
}
