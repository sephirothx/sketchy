import { PROTOCOL_HEADER, handleProtocolHeader } from "./protocol.ts";
import { noteUpdateStuckFromRest } from "./socket.ts";
import { reportSuspended, suspensionFromPayload } from "./suspension.ts";
const DEFAULT_TIMEOUT_MS = 8000;
const BINARY_TIMEOUT_MS = 20000;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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

  constructor(message: string, kind: "required" | "passkey" = "required") {
    super(401, message);
    this.name = "SecondFactorRequiredError";
    this.kind = kind;
  }
}

export class StepUpRequiredError extends ApiError {
  constructor(message: string) {
    super(403, message);
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
      const detail =
        (payload && typeof payload.detail === "string" && payload.detail)
        || `Request failed with ${response.status}`;
      if (response.status === 403 && response.headers.get(STEP_UP_HEADER)) {
        throw new StepUpRequiredError(detail);
      }
      const secondFactor = response.headers.get(SECOND_FACTOR_HEADER);
      if (response.status === 401 && secondFactor) {
        throw new SecondFactorRequiredError(
          detail,
          secondFactor === "passkey" ? "passkey" : "required",
        );
      }
      throw new ApiError(response.status, detail);
    }
    return payload as T;
  } finally {
    window.clearTimeout(timer);
  }
}
