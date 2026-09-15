import { useLayoutEffect, useRef } from "react";

import { ConnectionStatusBanner } from "./ConnectionStatusBanner";
import { EmailRecoveryReminder } from "./EmailRecoveryReminder";
import { XIcon } from "./icons";
import { placeNotices } from "../lib/appNotices";
import { reloadForUpdate } from "../lib/protocol";
import { useDrainSecondsLeft } from "../hooks/useServerNotices";
import { useGameStore } from "../store/gameStore";
import { useServerNoticesStore } from "../store/serverNoticesStore";
import { ui } from "../content/ui/index.ts";

/** Every banner at the top of the page, in one stack that reserves its own height.

They used to be separate `position: sticky; top: 0` siblings. Nothing made room
for them, so the viewport-sized screens - the phone's playing shell, which is
`position: fixed`, and the one-screen lobby - carried on laying themselves out
as if the banners were not there: the shell's header went under them, taps on
it landed on the banner, and the lobby's bottom actions were pushed off-screen.
Two banners at once also stuck to the same `top: 0` and covered each other.

So the stack publishes its height as `--banner-height`, and those screens
subtract it (#797). Inside a room the two notices that happen mid-game are not
banners at all - see `placeNotices` and `RoomNoticeChips`. */
export function AppBanners() {
  const stackRef = useRef<HTMLDivElement | null>(null);
  const inRoom = useGameStore((state) => state.roomId !== null);
  const shutdownNotice = useServerNoticesStore((state) => state.shutdownNotice);
  const paused = useServerNoticesStore((state) => state.paused);
  const restarted = useServerNoticesStore((state) => state.restarted);
  const serverFull = useServerNoticesStore((state) => state.serverFull);
  const updateRequired = useServerNoticesStore((state) => state.updateRequired);
  const connection = useServerNoticesStore((state) => state.connection);
  const setNotices = useServerNoticesStore((state) => state.set);
  const secondsLeft = useDrainSecondsLeft();

  useLayoutEffect(() => {
    const stack = stackRef.current;
    if (!stack) return;
    const root = document.documentElement;
    const publish = () => root.style.setProperty("--banner-height", `${stack.offsetHeight}px`);
    publish();
    // A banner wrapping to a second line on rotation changes the height as
    // surely as one appearing does, so it is the box that is watched, not the
    // list of banners.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(stack);
    return () => {
      observer?.disconnect();
      root.style.setProperty("--banner-height", "0px");
    };
  }, []);

  const { banners } = placeNotices({
    inRoom,
    updateRequired,
    serverFull: serverFull !== null,
    paused,
    draining: shutdownNotice !== null,
    restarted,
    connection,
  });

  return (
    <div className="app-banners" ref={stackRef}>
      {banners.map((notice) => {
        switch (notice) {
          case "update-required":
            return (
              <div key={notice} className="server-shutdown-banner is-update-required" role="alert">
                <span>{ui.app.thisTabOutDateCannotPlay}</span>
                <button
                  type="button"
                  onClick={() =>
                    reloadForUpdate({
                      storage: typeof sessionStorage === "undefined" ? null : sessionStorage,
                      reload: () => window.location.reload(),
                    })
                  }
                >
                  {ui.app.reload}
                </button>
              </div>
            );
          case "server-full":
            return (
              <div key={notice} className="server-shutdown-banner" role="status" aria-live="polite">
                {serverFull}
              </div>
            );
          case "paused":
            return (
              <div key={notice} className="server-shutdown-banner" role="status" aria-live="polite">
                {ui.app.newRoomsArePausedMaintenanceGames}
              </div>
            );
          case "drain":
            return (
              <div key={notice} className="server-shutdown-banner" role="status" aria-live="polite">
                {ui.app.serverUpdateInProgress({ seconds: secondsLeft })}
              </div>
            );
          case "restarted":
            return (
              <div key={notice} className="server-shutdown-banner is-restarted" role="status" aria-live="polite">
                <span>{ui.app.serverWasUpdatedBackAnyGame}</span>
                <button
                  type="button"
                  aria-label={ui.app.dismiss}
                  onClick={() => setNotices({ restarted: false })}
                >
                  <XIcon size={14} />
                </button>
              </div>
            );
          case "connection":
            return connection === "connected" ? null : (
              <ConnectionStatusBanner key={notice} status={connection} />
            );
        }
      })}
      <EmailRecoveryReminder />
    </div>
  );
}
