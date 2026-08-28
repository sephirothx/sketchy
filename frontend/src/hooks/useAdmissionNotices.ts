import { useEffect, useReducer } from "react";

import {
  announcementsAfter,
  NO_ANNOUNCEMENTS,
  type AdmissionAnnouncements,
} from "../lib/admissionAnnouncements";
import { socket } from "../lib/socket";
import { parsePausedNotice, parseShutdownNotice } from "../lib/shutdownNotice";

/** Admission changes as the server announces them, rather than as last fetched.

The operations page reads maintenance state when it mounts and after a command
it issued itself, which leaves it blind to exactly the case its shutdown guard
exists for: a drain another operator started, or a stop sent to the host. Both
are already broadcast to every socket, so the panel can be told rather than
asked — no polling, and no re-read racing the click it is meant to gate.

Everything here belongs to one connection, and `App.tsx` reads a reconnect the
same way: as the replacement server being up. The transitions live in
`lib/admissionAnnouncements.ts` so they are covered; this is the wiring.

The server stays the authority: a click that slips through the millisecond
between the announcement and the button is still refused with a 409. This is
about the panel not offering an action it knows cannot work. */
export function useAdmissionNotices(): AdmissionAnnouncements {
  const [announcements, announce] = useReducer(
    announcementsAfter,
    NO_ANNOUNCEMENTS,
  );

  useEffect(() => {
    const onShutdown = (payload: unknown) => {
      if (parseShutdownNotice(payload)) announce({ type: "draining" });
    };
    const onPaused = (payload: unknown) => {
      const notice = parsePausedNotice(payload);
      if (notice) announce({ type: "paused", paused: notice.paused });
    };
    const onConnect = () => announce({ type: "connect" });
    socket.on("server_shutdown", onShutdown);
    socket.on("server_paused", onPaused);
    socket.on("connect", onConnect);
    return () => {
      socket.off("server_shutdown", onShutdown);
      socket.off("server_paused", onPaused);
      socket.off("connect", onConnect);
    };
  }, []);

  return announcements;
}
