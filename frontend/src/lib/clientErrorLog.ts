/** A bounded tail of what went wrong in this tab, for a bug report to carry.

Nothing in the app listened for uncaught errors before this. That is fine for
running the game - a thrown error is already visible as a broken screen - but it
is exactly what is missing when somebody files a report: the description says
"the timer kept going", and the one fact that would explain it went to a console
nobody will ever read.

Deliberately a ring buffer and nothing else. It never sends anything on its own,
never persists, and is read only when a player chooses to attach it. An error log
that phoned home would be telemetry, which is a different thing needing a
different conversation. */

export type ClientErrorKind = "error" | "unhandled" | "console" | "socket";

export interface ClientErrorEntry {
  /** ISO-8601, so the server can line it up against its own clock. */
  at: string;
  kind: ClientErrorKind;
  message: string;
}

/** Twenty is enough to see what led to a failure. A page erroring in a loop
    would otherwise turn one report into a log shipment. */
export const MAX_ENTRIES = 20;
/** Long enough for a stack's first frames, short enough that twenty of them
    stay well inside the report's context budget. */
export const MAX_MESSAGE_CHARS = 500;

const entries: ClientErrorEntry[] = [];
let installed = false;
// A throw inside the recorder would reach console.error and be recorded again.
// One flag is cheaper than reasoning about how deep that could go.
let recording = false;

function describe(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) {
    return value.stack ? `${value.name}: ${value.message}\n${value.stack}` : `${value.name}: ${value.message}`;
  }
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    // A circular or exotic value is still worth a line saying it happened.
    return String(value);
  }
}

/** Add one entry, oldest dropped once the buffer is full. */
export function recordClientError(kind: ClientErrorKind, message: unknown): void {
  if (recording) return;
  recording = true;
  try {
    entries.push({
      at: new Date().toISOString(),
      kind,
      message: describe(message).slice(0, MAX_MESSAGE_CHARS),
    });
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
  } finally {
    recording = false;
  }
}

/** The tail, oldest first. A copy, so a caller cannot mutate the buffer. */
export function recentClientErrors(): ClientErrorEntry[] {
  return entries.map((entry) => ({ ...entry }));
}

/** Start listening. Safe to call twice; only the first call does anything. */
export function installClientErrorLog(): void {
  if (installed) return;
  installed = true;

  window.addEventListener("error", (event) => {
    // A failed <img> or <script> also fires this, with no `error` object. The
    // filename is the useful part there.
    const detail = event.error ?? event.message ?? "unknown error";
    const where = event.filename ? ` (${event.filename}:${event.lineno})` : "";
    recordClientError("error", `${describe(detail)}${where}`);
  });

  window.addEventListener("unhandledrejection", (event) => {
    recordClientError("unhandled", event.reason ?? "unhandled rejection");
  });

  // Wrapped rather than replaced: whatever the console would have shown still
  // shows, because a developer watching it live must not lose anything.
  const original = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    recordClientError("console", args.map(describe).join(" "));
    original(...args);
  };
}

/** Test seam: forget everything and allow a fresh install. */
export function resetClientErrorLog(): void {
  entries.length = 0;
  installed = false;
  recording = false;
}
