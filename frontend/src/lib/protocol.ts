/** The socket contract version this bundle speaks.

Must match `PROTOCOL_VERSION` in `backend/app/protocol.py`. Both ends deploy
together, so the only client that ever sees a mismatch is one that was already
open across a deploy - a tab left on a sleeping laptop, most often. The server
answers such a socket with `upgrade_required` rather than refusing it, and the
client reloads onto the build being served. */
export const PROTOCOL_VERSION = 7;

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
