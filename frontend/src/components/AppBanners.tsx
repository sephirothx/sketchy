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
    let written = -1;
    const publish = () => {
      const height = stack.offsetHeight;
      if (height === written) return;
      written = height;
      root.style.setProperty("--banner-height", `${height}px`);
    };
    publish();
    // A banner coming or going is a change to the stack's DOM, and is measured
    // as it happens - before the browser lays the page out for it. The screens
    // that subtract this height are the whole page's height, so writing it
    // only once the frame had been laid out with the banner in - from the
    // stack's ResizeObserver, as this used to - grew the page past the window
    // and shrank it back inside one frame, after `html`'s own observer
    // (lib/scrollbarWidth.ts) had been told of the first change. A second
    // resize the browser cannot deliver that frame is reported on `window` as
    // a "ResizeObserver loop" error, and the client error log carried one into
    // every bug report filed after a banner.
    const changes = new MutationObserver(publish);
    changes.observe(stack, { childList: true, subtree: true, characterData: true, attributes: true });
    // What is not a change to the DOM - a banner wrapping to a second line on
    // rotation, a web font arriving - shows only once it is laid out, and is
    // written a frame later, for the same reason.
    let frame = 0;
    const resizes =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(publish);
          });
    resizes?.observe(stack);
    return () => {
      changes.disconnect();
      resizes?.disconnect();
      cancelAnimationFrame(frame);
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
            // Rendered below, outside the list: the pad it opens outlives the banner.
            return null;
        }
      })}
      <ConnectionStatusBanner status={banners.includes("connection") ? connection : "connected"} />
      <EmailRecoveryReminder />
    </div>
  );
}
