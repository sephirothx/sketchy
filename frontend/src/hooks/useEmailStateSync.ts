import { useEffect } from "react";

import { socket } from "../lib/socket";
import { useAuthStore } from "../store/authStore";
import { useEmailStateStore } from "../store/emailStateStore";

/** Keep the account's recovery address state current in every open tab.

App-wide rather than inside the reminder, because the reminder is not the only
reader and is not always mounted to listen. Re-read on the account, since
registering or signing in replaces whose address this is - and a guest has
none. Re-read on `email_state_changed`, which the server sends every tab of the
account after the address is offered or confirmed or the reminder is closed,
and on reconnecting, which is how a tab hears about a change it was offline
for. */
export function useEmailStateSync() {
  const refresh = useEmailStateStore((state) => state.refresh);
  const accountId = useAuthStore((state) =>
    state.hasResolved && state.user !== null && !state.user.isAnonymous
      ? state.user.id
      : null,
  );

  useEffect(() => {
    void refresh(accountId);
  }, [refresh, accountId]);

  useEffect(() => {
    const again = () => void refresh();
    socket.on("email_state_changed", again);
    socket.on("connect", again);
    return () => {
      socket.off("email_state_changed", again);
      socket.off("connect", again);
    };
  }, [refresh]);
}
