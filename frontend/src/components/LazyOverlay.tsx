import { useEffect, useState, type ComponentType } from "react";

import { ui } from "../content/ui/index.ts";

/** An overlay fetched as its own chunk, and what shows if it cannot be (#475).

`React.lazy` throws a failed import to the nearest error boundary, and the
overlays render outside the room's own: a player opening Settings mid-game on
a connection that had just dropped lost the whole room to the crash page, and
`lazy` keeps the rejected promise, so it failed again once the connection was
back. This loads the chunk itself instead: nothing while it arrives, and a
notice if it does not, with the room underneath untouched.

Its button reloads the page rather than importing again: a browser keeps a
failed dynamic import for the life of the document, so a second `import()`
of the same chunk fails at once however good the connection has become. The
overlay's address is in the URL, so the reload opens it, and a room reconnects
to its seat as it does after any reload. */
export function lazyOverlay<P extends object>(
  load: () => Promise<ComponentType<P>>,
): ComponentType<P> {
  let loaded: ComponentType<P> | null = null;
  return function LazyOverlay(props: P) {
    const [component, setComponent] = useState<ComponentType<P> | null>(() => loaded);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
      if (loaded) return;
      let current = true;
      load().then(
        (next) => {
          loaded = next;
          if (current) setComponent(() => next);
        },
        () => {
          if (current) setFailed(true);
        },
      );
      return () => {
        current = false;
      };
    }, []);

    const Loaded = component ?? loaded;
    if (Loaded) return <Loaded {...props} />;
    if (!failed) return null;
    return (
      <div className="app-toast lazy-overlay-notice" role="alert">
        <span>{ui.app.couldNotOpenThis}</span>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => window.location.reload()}
        >
          {ui.app.tryAgain}
        </button>
      </div>
    );
  };
}
