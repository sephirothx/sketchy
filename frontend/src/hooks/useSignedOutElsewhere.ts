import { useEffect } from "react";

import { socket } from "../lib/socket";
import { isSigningOut, useAuthStore } from "../store/authStore";

/** A session revoked from another device - a sign-out everywhere, a password
change, a device revoked from the list - closes this tab's socket with a
`session_superseded` notice (#1007), and so does the account being deleted. The room screen navigates away on its own;
here, wherever the tab is, the account is re-read and the socket handshakes
again with whatever cookie is left - the new one on the device that acted,
none on the ones signed out. */
export function useSignedOutElsewhere(): void {
  const adoptFromServer = useAuthStore((state) => state.adoptFromServer);
  useEffect(() => {
    const onSuperseded = (data: { code?: string } | undefined) => {
      // An account deleted - by its owner on another device, or by an
      // operator - closes its sockets the same way with `account_deleted`.
      // Only the room screen listened for it, so a lobby tab reconnected a
      // second later as nobody while the store still held the deleted
      // account (#1056). Re-read here too: the cookie is gone, so the tab
      // becomes whatever the server now says it is.
      const code = data?.code;
      if ((code === "signed_out" || code === "account_deleted") && !isSigningOut()) {
        void adoptFromServer();
      }
    };
    socket.on("session_superseded", onSuperseded);
    return () => {
      socket.off("session_superseded", onSuperseded);
    };
  }, [adoptFromServer]);
}
