import { useEffect } from "react";

import { onSettingsSyncError } from "../lib/accountSettingsSync";
import { useToast } from "../lib/toast";

/** Where a refused settings write is reported, whichever screen made it.

A setting applies the moment it changes and is saved to the account behind the
player's back (R-SET-05), so a refused save is the one thing about it they
need telling. It used to be the Settings panel that listened - which meant a
save made from anywhere else, the lobby's language flag first, failed in
silence. Mounted once, under the toasts, for the whole app. */
export function SettingsSyncNotices() {
  const { notify } = useToast();
  useEffect(() => {
    onSettingsSyncError((message) => notify(message, "error"));
    return () => onSettingsSyncError(null);
  }, [notify]);
  return null;
}
