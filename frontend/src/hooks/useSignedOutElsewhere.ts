import { useEffect } from "react";

import { socket } from "../lib/socket";
import { isSigningOut, useAuthStore } from "../store/authStore";

/** A session revoked from another device - a sign-out everywhere, a password
change, a device revoked from the list - closes this tab's socket with a
`session_superseded` notice (#1007). The room screen navigates away on its own;
here, wherever the tab is, the account is re-read and the socket handshakes
again with whatever cookie is left - the new one on the device that acted,
none on the ones signed out. */
export function useSignedOutElsewhere(): void {
  const adoptFromServer = useAuthStore((state) => state.adoptFromServer);
  useEffect(() => {
    const onSuperseded = (data: { code?: string } | undefined) => {
      if (data?.code === "signed_out" && !isSigningOut()) void adoptFromServer();
    };
    socket.on("session_superseded", onSuperseded);
    return () => {
      socket.off("session_superseded", onSuperseded);
    };
  }, [adoptFromServer]);
}
