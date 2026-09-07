/** The tab is out of date and the one reload it was allowed did not fix it (#476).

Reached from either place a version is compared: the socket handshake's
`upgrade_required`, and the protocol header on a REST response. Both take the
reload-once path in `protocol.ts`; when that path reports "stuck" - the same
server version seen again after a reload - the bundle is not updating on its
own, and the player is told rather than left on a tab whose every command is
refused. Module state rather than a store: it is set once, from outside React,
and never cleared except by leaving the page. */

let required = false;
const listeners = new Set<() => void>();

/** Record that the tab needs an update it could not fetch itself. */
export function markUpdateRequired(): void {
  if (required) return;
  required = true;
  listeners.forEach((listener) => listener());
}

export function isUpdateRequired(): boolean {
  return required;
}

/** Subscribe to the flag being raised; called at once if it already is. */
export function onUpdateRequired(listener: () => void): () => void {
  listeners.add(listener);
  if (required) listener();
  return () => {
    listeners.delete(listener);
  };
}

/** Testing only: the page-load state, for a suite that shares one module. */
export function resetUpdateRequiredForTests(): void {
  required = false;
}
