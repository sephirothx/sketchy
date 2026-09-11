import { useEffect, useRef } from "react";

import { acknowledgeReportsReviewed, countReportsReviewed } from "../lib/moderation";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import { ui } from "../content/ui/index.ts";

/** Tells a reporter their report was looked at.

Reporting into silence is what teaches people not to bother, and every other
moderation message in the app goes to the person complained about rather than
the person who complained. This is the one that closes the loop.

It says a count and nothing else. What was decided belongs to the reported
player, and an outcome handed back to whoever asked about them would turn a
report into a way of finding things out about somebody (R-MOD-20).

A toast rather than a modal: a report you filed days ago being reviewed is
worth knowing and is not worth interrupting a game for. It is acknowledged as
it is shown, so it is said once - the count would otherwise greet them on
every page load forever. */
export function ReportsReviewedNotice() {
  const { notify } = useToast();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const isGuest = useAuthStore((state) => state.user?.isAnonymous ?? true);
  // Whose reports have already been asked about, so a re-render or a second
  // mount does not ask again for the same account.
  const askedFor = useRef<string | null>(null);

  useEffect(() => {
    // A guest can report (R-MOD-01), but a guest identity is a browser: the
    // account that filed it may not be the one reading this.
    if (!userId || isGuest || askedFor.current === userId) return;
    askedFor.current = userId;
    let cancelled = false;

    void (async () => {
      try {
        // The cheap question first, so the usual answer - nothing to say -
        // costs no write.
        const { count, reportIds } = await countReportsReviewed();
        if (cancelled || count < 1) return;
        // Shown *before* it is recorded as shown. Recording first loses the
        // message whenever the render does not happen - signing out while
        // the request is in flight, the effect torn down - and a report
        // marked as told that nobody was told about is never announced
        // again. This way the worst case is being thanked twice.
        notify(ui.reportsReviewedNotice.reportsReviewed({ count }), "info", 12000);
        // Exactly the ones that message was about. A report decided since the
        // read is not in the list, so it keeps its turn.
        await acknowledgeReportsReviewed(reportIds);
      } catch {
        // A report that was reviewed is not news worth an error for. It will
        // be said on the next visit instead.
        askedFor.current = null;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userId, isGuest, notify]);

  return null;
}
