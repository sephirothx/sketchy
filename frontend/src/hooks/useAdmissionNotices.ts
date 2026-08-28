import { useEffect, useState } from "react";

import { socket } from "../lib/socket";
import { parsePausedNotice, parseShutdownNotice } from "../lib/shutdownNotice";

/** Admission changes as the server announces them, rather than as last fetched.

The operations page reads maintenance state when it mounts and after a command
it issued itself, which leaves it blind to exactly the case its shutdown guard
exists for: a drain another operator started, or a stop sent to the host. Both
are already broadcast to every socket, so the panel can be told rather than
asked — no polling, and no re-read racing the click it is meant to gate.

The server stays the authority: a click that slips through the millisecond
between the announcement and the button is still refused with a 409. This is
about the panel not offering an action it knows cannot work. */
export function useAdmissionNotices(): {
  draining: boolean;
  paused: boolean | null;
} {
  // A drain is one-way, so this only ever goes true.
  const [draining, setDraining] = useState(false);
  // Null until something says otherwise, so a page that has heard nothing
  // defers to whatever it loaded rather than asserting "not paused".
  const [paused, setPaused] = useState<boolean | null>(null);

  useEffect(() => {
    const onShutdown = (payload: unknown) => {
      if (parseShutdownNotice(payload)) setDraining(true);
    };
    const onPaused = (payload: unknown) => {
      const notice = parsePausedNotice(payload);
      if (notice) setPaused(notice.paused);
    };
    socket.on("server_shutdown", onShutdown);
    socket.on("server_paused", onPaused);
    return () => {
      socket.off("server_shutdown", onShutdown);
      socket.off("server_paused", onPaused);
    };
  }, []);

  return { draining, paused };
}
