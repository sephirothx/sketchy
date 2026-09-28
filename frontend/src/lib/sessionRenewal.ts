/** Telling this browser's other tabs that its session cookie was renewed.

A password change or reset revokes every session and issues the acting tab a
new one; the server closes the browser's other sockets a few seconds later so
they reconnect with it (#1246). A response slower than that grace let a tab
reconnect first, with the revoked cookie, as nobody - and nothing made it look
again once the new cookie landed (#1295 review). The acting tab says so here
once the response is in hand, and every other tab re-reads the account and
handshakes again. */

const CHANNEL = "sketchy-session";
const RENEWED = "renewed";
// A channel hears every other channel of its name, this tab's own listener
// included, and the acting tab has already rebound itself.
const THIS_TAB = Math.random().toString(36).slice(2);

/** Tell the other tabs; nothing when the browser has no channel to do it. */
export function announceSessionRenewed(): void {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(CHANNEL);
  channel.postMessage({ type: RENEWED, from: THIS_TAB });
  channel.close();
}

/** Call `listener` whenever another tab renews the session; returns the stop. */
export function onSessionRenewed(listener: () => void): () => void {
  if (typeof BroadcastChannel === "undefined") return () => {};
  const channel = new BroadcastChannel(CHANNEL);
  channel.onmessage = (event: MessageEvent) => {
    if (event.data?.type === RENEWED && event.data.from !== THIS_TAB) listener();
  };
  return () => channel.close();
}
