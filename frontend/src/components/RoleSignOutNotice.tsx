import { useEffect } from "react";

import { socket } from "../lib/socket";
import { useToast } from "../lib/toast";
import { ui } from "../content/ui/index.ts";

/** Say why a promotion signed this tab out (#1436, R-AUTH-20).

A role given outright ends every session the account holds, so the new
moderator signs in again and produces a code. The tab is re-read as signed
out by `useSignedOutElsewhere`; this says why, once, where a sign-out that
came with no word would look like a fault. What the role is lands in the
inbox for after they sign back in. */
export function RoleSignOutNotice() {
  const { notify } = useToast();
  useEffect(() => {
    const onSuperseded = (data: { code?: string } | undefined) => {
      if (data?.code === "role_changed") notify(ui.inbox.signedOutForRole, "info", 12000);
    };
    socket.on("session_superseded", onSuperseded);
    return () => {
      socket.off("session_superseded", onSuperseded);
    };
  }, [notify]);
  return null;
}
