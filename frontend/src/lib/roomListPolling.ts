export type RoomListVisibility = "hidden" | "visible";

export interface RoomListPollingEnvironment {
  visibilityState(): RoomListVisibility;
  addVisibilityChangeListener(listener: () => void): void;
  removeVisibilityChangeListener(listener: () => void): void;
  setInterval(listener: () => void, intervalMs: number): number;
  clearInterval(intervalId: number): void;
}

function browserEnvironment(): RoomListPollingEnvironment {
  return {
    visibilityState: () =>
      document.visibilityState === "hidden" ? "hidden" : "visible",
    addVisibilityChangeListener: (listener) =>
      document.addEventListener("visibilitychange", listener),
    removeVisibilityChangeListener: (listener) =>
      document.removeEventListener("visibilitychange", listener),
    setInterval: (listener, intervalMs) =>
      window.setInterval(listener, intervalMs),
    clearInterval: (intervalId) => window.clearInterval(intervalId),
  };
}

/**
 * Start one non-overlapping refresh loop while the document is visible.
 *
 * The refresh callback owns user-facing error handling. Rejections are
 * suppressed here so a failed refresh does not create an unhandled promise or
 * stop later polling attempts.
 */
export function startVisibilityAwarePolling(
  refresh: () => Promise<void>,
  intervalMs: number,
  environment: RoomListPollingEnvironment = browserEnvironment(),
): () => void {
  let disposed = false;
  let refreshInFlight = false;
  let intervalId: number | null = null;
  let visibility = environment.visibilityState();

  function clearPollingInterval() {
    if (intervalId === null) return;
    environment.clearInterval(intervalId);
    intervalId = null;
  }

  function triggerRefresh() {
    if (disposed || refreshInFlight) return;
    refreshInFlight = true;
    void Promise.resolve()
      .then(refresh)
      .catch(() => undefined)
      .finally(() => {
        refreshInFlight = false;
      });
  }

  function startPollingInterval() {
    clearPollingInterval();
    if (disposed || visibility === "hidden") return;
    intervalId = environment.setInterval(triggerRefresh, intervalMs);
  }

  function handleVisibilityChange() {
    const nextVisibility = environment.visibilityState();
    if (nextVisibility === visibility) return;
    visibility = nextVisibility;
    clearPollingInterval();
    if (visibility === "visible") {
      triggerRefresh();
      startPollingInterval();
    }
  }

  environment.addVisibilityChangeListener(handleVisibilityChange);
  if (visibility === "visible") {
    triggerRefresh();
    startPollingInterval();
  }

  return () => {
    if (disposed) return;
    disposed = true;
    clearPollingInterval();
    environment.removeVisibilityChangeListener(handleVisibilityChange);
  };
}
