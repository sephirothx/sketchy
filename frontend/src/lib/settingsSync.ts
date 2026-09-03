import type { AccountSettings } from "./userSettings.ts";

/**
 * Sending an immediately-applied preference to the account (R-SET-05).
 *
 * Every row in Settings applies the moment it changes, so there is no Save to
 * hang a single write off. Writes are merged and flushed together instead: a
 * slider dragged across its range is one request rather than twenty, and two
 * switches toggled in the same breath cost one round trip.
 *
 * Guests never reach the network - their settings are the browser's, by
 * R-SET-03 - and a failure is reported rather than retried: the value is
 * already applied locally, so the honest thing to say is that it did not
 * follow them to their other devices.
 */
export interface SettingsSyncTransport {
  send: (batch: Partial<AccountSettings>) => Promise<unknown>;
  /** False for a guest, or before the account has resolved. */
  canSync: () => boolean;
  /** How long a change waits for company before it is sent. */
  delayMs: number;
  setTimer?: (callback: () => void, delayMs: number) => unknown;
  clearTimer?: (handle: unknown) => void;
}

export interface SettingsSync {
  queue: (change: Partial<AccountSettings>) => void;
  /** Send whatever is waiting now; resolves once it has been answered. */
  flush: () => Promise<void>;
  /** Where a refused write is reported. One listener: the open pane. */
  onError: (handler: ((message: string) => void) | null) => void;
  pendingKeys: () => string[];
}


export function createSettingsSync(transport: SettingsSyncTransport): SettingsSync {
  const setTimer = transport.setTimer ?? ((callback, delay) => setTimeout(callback, delay));
  const clearTimer = transport.clearTimer ?? ((handle) => clearTimeout(handle as number));
  let pending: Partial<AccountSettings> = {};
  let timer: unknown = undefined;
  let inFlight: Promise<void> | null = null;
  let report: ((message: string) => void) | null = null;

  function schedule(): void {
    if (timer !== undefined) clearTimer(timer);
    timer = setTimer(() => {
      timer = undefined;
      void flush();
    }, transport.delayMs);
  }

  async function flush(): Promise<void> {
    if (timer !== undefined) {
      clearTimer(timer);
      timer = undefined;
    }
    // One request at a time, in order: a change made while an earlier batch
    // is in the air waits for it, so two writes cannot overtake each other
    // and leave the account holding the older value.
    if (inFlight) await inFlight;
    const batch = pending;
    pending = {};
    const keys = Object.keys(batch);
    if (keys.length === 0 || !transport.canSync()) return;
    inFlight = transport.send(batch).then(
      () => undefined,
      () => {
        report?.(
          "That change applies here, but could not be saved to your account. Your other devices will not see it.",
        );
      },
    );
    try {
      await inFlight;
    } finally {
      inFlight = null;
    }
    if (Object.keys(pending).length > 0) schedule();
  }

  return {
    queue(change) {
      if (!transport.canSync()) return;
      pending = { ...pending, ...change };
      schedule();
    },
    flush,
    onError(handler) {
      report = handler;
    },
    pendingKeys: () => Object.keys(pending),
  };
}
