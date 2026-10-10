import { useEffect } from "react";

import { onConnectSpread, onEntryRefused, socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { useInboxStore } from "../store/inboxStore";

/** Keep the inbox current wherever the player is (#1436, R-INBOX-01).

Mounted once, app-wide. Reads when the account is known or changes, when
`inbox_changed` arrives - the server's word that an entry was written or
read, in this tab or another - and on every (re)connection, because a push
reaches only the sockets that are there when it is sent: a tab between a drop
and the reconnect heard nothing, and catches up by reading (R-CONN-14). And
when a seat is refused over an unread warning, so the dialog shows. */
export function useInboxSync(): void {
  const userId = useAuthStore((state) => (state.hasResolved ? state.user?.id ?? null : undefined));

  useEffect(() => {
    if (userId === undefined) return;
    const store = useInboxStore.getState();
    if (userId === null) {
      store.clear();
      return;
    }
    void store.refresh(userId);
    const read = () => void useInboxStore.getState().refresh(userId);
    socket.on("inbox_changed", read);
    const stopOnConnect = onConnectSpread(read);
    // Refused a seat over a warning this tab had not shown: read, and the
    // dialog appears (R-INBOX-04).
    const stopOnRefusal = onEntryRefused((code) => {
      if (code === "warning_unread") read();
    });
    return () => {
      socket.off("inbox_changed", read);
      stopOnConnect();
      stopOnRefusal();
    };
  }, [userId]);
}
