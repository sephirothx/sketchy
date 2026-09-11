import type { ErrorCode } from "../types.ts";
import type { RefusalParams } from "./refusals.ts";
import { PROTOCOL_HEADER, handleProtocolHeader } from "./protocol.ts";
import { noteUpdateStuckFromRest } from "./socket.ts";
import { reportSuspended, suspensionFromPayload } from "./suspension.ts";
const DEFAULT_TIMEOUT_MS = 8000;
const BINARY_TIMEOUT_MS = 20000;

export class ApiError extends Error {
  readonly status: number;

  /** Why the server refused, as one of the enumerated codes. Absent only for
      a failure with no response body - a timeout, a proxy, a 502. Branch on
      this and write the sentence with `refusalText`; `message` is the
      server's English and is for a log, never for a player (R-I18N-01). */
  readonly errorCode?: ErrorCode;

  /** The values that sentence needs - a limit, a count, a reason slug. Never
      rendered text. */
  readonly params?: RefusalParams;

  /** The payload field that failed validation, for binding to a form. */
  readonly field?: string;

  /** When the server knows trying again could work. */
  readonly retryAfterMs?: number;

  constructor(
    status: number,
    message: string,
    refusal: {
      errorCode?: ErrorCode;
      params?: RefusalParams;
      field?: string;
      retryAfterMs?: number;
    } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = refusal.errorCode;
    this.params = refusal.params;
    this.field = refusal.field;
    this.retryAfterMs = refusal.retryAfterMs;
  }
}

/** Pull the refusal out of a response body, whatever shape it came in.

An unconverted route still answers `{"detail": "..."}`, and a body that is not
JSON at all answers nothing; both leave `errorCode` unset, which is exactly
what `refusalText`'s fallback is for. */
function refusalFrom(payload: unknown): {
  errorCode?: ErrorCode;
  params?: RefusalParams;
  field?: string;
  retryAfterMs?: number;
} {
  if (!payload || typeof payload !== "object") return {};
  const body = payload as Record<string, unknown>;
  return {
    errorCode: typeof body.errorCode === "string" ? (body.errorCode as ErrorCode) : undefined,
    params:
      body.params && typeof body.params === "object"
        ? (body.params as RefusalParams)
        : undefined,
    field: typeof body.field === "string" ? body.field : undefined,
    retryAfterMs: typeof body.retryAfterMs === "number" ? body.retryAfterMs : undefined,
  };
}

/** The refusal fields an `ApiError` subclass passes through unchanged. */
type RefusalFields = {
  errorCode?: ErrorCode;
  params?: RefusalParams;
  field?: string;
  retryAfterMs?: number;
};

/** The header naming a 403 that means *this caller has no account*. */
export const ACCOUNT_REQUIRED_HEADER = "X-Sketchy-Account-Required";

/** A 403 the server has named, rather than one a caller has guessed at.

Its own type for the same reason `StepUpRequiredError` has one: a status is
not a reason, and the callers that act on this refusal act on it *hard* - the
friends list treats it as "there is no list" and shows an empty one. A
suspension is also a 403 on the same path. */
export class AccountRequiredError extends ApiError {
  constructor(message: string, refusal: RefusalFields = {}) {
    super(403, message, refusal);
    // Read by `isNoFriendListRefusal`, which lives in a module with no
    // runtime imports and so cannot name this class.
    this.name = "AccountRequiredError";
  }
}

/**
 * The header a staff refusal carries when it means *not yet* rather than
 * *not you* (R-AUTH-21): the action needs the second factor proved again.
 * Distinguished by a header rather than by reading the sentence, so the
 * wording can change without breaking the branch that depends on it.
 */
export const STEP_UP_HEADER = "x-sketchy-step-up";

/**
 * Sent with a 401 from `POST /api/auth/login` when the account holds a second
 * factor and no code was given. Distinguishes "now type the code" from "that
 * password is wrong", which look identical in the status alone.
 */
export const SECOND_FACTOR_HEADER = "x-sketchy-second-factor";

export class SecondFactorRequiredError extends ApiError {
  /** Which one the account holds. `passkey` means the password route cannot
      finish at all — there is no code to type, and the form has to offer the
      passkey instead of a field (R-AUTH-23). */
  readonly kind: "required" | "passkey";

  constructor(
    message: string,
    kind: "required" | "passkey" = "required",
    refusal: RefusalFields = {},
  ) {
    super(401, message, refusal);
    this.name = "SecondFactorRequiredError";
    this.kind = kind;
  }
}

export class StepUpRequiredError extends ApiError {
  constructor(message: string, refusal: RefusalFields = {}) {
    super(403, message, refusal);
    this.name = "StepUpRequiredError";
  }
}

/**
 * Same-origin JSON fetch that carries the session cookie.
 *
 * `credentials: "same-origin"` is the browser default for same-origin requests
 * and is stated here only to make the dependency on the session cookie obvious
 * at the call site. The token itself is HttpOnly and never visible here.
 */
/** Compare the server's version stamp on a response with this bundle (#476).

Read on every response, success or not, because the stale tab's next request
is whichever one it makes. A skew takes the same reload-once path as the
socket's notice; a second one after that reload means the bundle is not
updating, and the page says so rather than reloading again. */
function checkProtocol(response: Response): void {
  handleProtocolHeader(response.headers.get(PROTOCOL_HEADER), {
    storage: typeof sessionStorage === "undefined" ? null : sessionStorage,
    reload: () => window.location.reload(),
    onStuck: noteUpdateStuckFromRest,
  });
}

export async function apiBinaryRequest(
  path: string,
  options: { timeoutMs?: number } = {},
): Promise<ArrayBuffer> {
  // A drawing can reach a few hundred kilobytes, which is a slow read on a
  // phone, so this waits longer than the JSON default.
  const { timeoutMs = BINARY_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      signal: controller.signal,
    });
    checkProtocol(response);
    if (!response.ok) {
      throw new ApiError(response.status, `Request failed with ${response.status}`);
    }
    return await response.arrayBuffer();
  } finally {
    window.clearTimeout(timer);
  }
}

export async function apiRequest<T>(
  path: string,
  options: { method?: string; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });

    checkProtocol(response);
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;

    if (!response.ok) {
      // A suspension is raised here rather than left to each caller: it can
      // refuse any request, and the player is owed the reason wherever they
      // happened to be when it landed.
      const suspension = suspensionFromPayload(payload);
      if (suspension) reportSuspended(suspension);
      // Not copy: the error's own message, for logs. A screen says what failed
      // through refusalText and a catalogue fallback, never through this.
      const detail =
        (payload && typeof payload.detail === "string" && payload.detail)
        || `Request failed with ${response.status}`;
      const refusal = refusalFrom(payload);
      if (response.status === 403 && response.headers.get(STEP_UP_HEADER)) {
        throw new StepUpRequiredError(detail, refusal);
      }
      // "You need an account for this", told apart from every other 403 by
      // the server rather than guessed from the status - a suspension is one
      // too, and reads the same way from here (R-FRIEND-03).
      if (response.status === 403 && response.headers.get(ACCOUNT_REQUIRED_HEADER)) {
        throw new AccountRequiredError(detail, refusal);
      }
      const secondFactor = response.headers.get(SECOND_FACTOR_HEADER);
      if (response.status === 401 && secondFactor) {
        throw new SecondFactorRequiredError(
          detail,
          secondFactor === "passkey" ? "passkey" : "required",
          refusal,
        );
      }
      throw new ApiError(response.status, detail, refusal);
    }
    return payload as T;
  } finally {
    window.clearTimeout(timer);
  }
}
