/** The socket contract version this bundle speaks.

Must match `PROTOCOL_VERSION` in `backend/app/protocol.py`. Both ends deploy
together, so the only client that ever sees a mismatch is one that was already
open across a deploy - a tab left on a sleeping laptop, most often. The server
answers such a socket with `upgrade_required` rather than refusing it, and the
client reloads onto the build being served. Until it does, the server refuses
every command the socket sends and closes it after a few seconds (#476), so
a reload is the only way forward - and the same number rides every REST
response in `PROTOCOL_HEADER`, so a tab that is not on a socket is caught by
its next request. */
export const PROTOCOL_VERSION = 16;

/** The response header every REST answer carries the server's version in. */
export const PROTOCOL_HEADER = "x-sketchy-protocol";

/** Where the last upgrade reload is remembered, so it can happen only once. */
const RELOAD_MARKER_KEY = "sketchy:upgrade-reload";

export interface UpgradeRequiredNotice {
  reason?: string;
  expected?: number;
  received?: number;
}

/** Reload onto the current build, at most once per server version.

`index.html` is served `no-cache` precisely so a reload lands on the new
bundle. But if it somehow does not - a proxy ignoring the header, a service
worker serving a stale shell - an unguarded reload would spin forever, turning
a recoverable version skew into an unusable page. So the server version we
reloaded for is recorded first, and a second notice naming the same version is
reported rather than acted on. */
export function handleUpgradeRequired(
  notice: UpgradeRequiredNotice | undefined,
  environment: {
    storage?: Pick<Storage, "getItem" | "setItem"> | null;
    reload: () => void;
    onStuck?: (notice: UpgradeRequiredNotice | undefined) => void;
  },
): boolean {
  const expected = String(notice?.expected ?? "unknown");
  let alreadyReloaded: boolean;
  try {
    alreadyReloaded = environment.storage?.getItem(RELOAD_MARKER_KEY) === expected;
  } catch {
    // A browser refusing session storage is not a reason to skip the reload;
    // it only means this page load cannot tell it has already tried one.
    alreadyReloaded = false;
  }

  if (alreadyReloaded) {
    environment.onStuck?.(notice);
    return false;
  }

  try {
    environment.storage?.setItem(RELOAD_MARKER_KEY, expected);
  } catch {
    // Ignored for the same reason.
  }
  environment.reload();
  return true;
}

/** Compare the version a REST response was stamped with against this bundle.

A different integer takes the same reload-once path as the socket notice,
with the same marker, so the two cannot between them reload twice. A header
that is absent or not an integer is ignored rather than treated as a skew: a
proxy that strips unknown headers, or a captive portal answering in the
server's place, must not reload the page. Returns whether a reload was asked
for. */
export function handleProtocolHeader(
  value: string | null | undefined,
  environment: Parameters<typeof handleUpgradeRequired>[1],
): boolean {
  if (typeof value !== "string" || !/^\d+$/.test(value.trim())) return false;
  const expected = Number(value.trim());
  if (!Number.isSafeInteger(expected) || expected === PROTOCOL_VERSION) return false;
  return handleUpgradeRequired(
    { reason: "The server was updated.", expected, received: PROTOCOL_VERSION },
    environment,
  );
}

/** Reload on request, forgetting the one automatic reload already spent.

The marker exists to stop an *automatic* loop. A player pressing Reload has
decided to try again, and if the bundle still does not update the notice
will land here once more rather than reloading on its own. */
export function reloadForUpdate(environment: {
  storage?: Pick<Storage, "removeItem"> | null;
  reload: () => void;
}): void {
  try {
    environment.storage?.removeItem(RELOAD_MARKER_KEY);
  } catch {
    // The reload happens regardless; only the marker's reset is lost.
  }
  environment.reload();
}
