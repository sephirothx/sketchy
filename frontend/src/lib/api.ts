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
 * Same-origin JSON fetch that carries the session cookie.
 *
 * `credentials: "same-origin"` is the browser default for same-origin requests
 * and is stated here only to make the dependency on the session cookie obvious
 * at the call site. The token itself is HttpOnly and never visible here.
 */
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

    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;

    if (!response.ok) {
      const detail =
        (payload && typeof payload.detail === "string" && payload.detail)
        || `Request failed with ${response.status}`;
      throw new ApiError(response.status, detail);
    }
    return payload as T;
  } finally {
    window.clearTimeout(timer);
  }
}
