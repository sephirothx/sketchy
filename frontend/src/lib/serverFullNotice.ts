/** What a socket turned away at the handshake is told, in the reader's language.

`server_full` names the ceiling that turned it away (#1232): the server's own,
or this account's - a player with too many tabs open. The payload's `reason` is
English, for a log; the sentence is written here (R-I18N-01). A `limit` this
build does not know, a newer server's, reads as the server being full, which is
still true enough to act on. */
import { ui } from "../content/ui/index.ts";

export interface ServerFullNotice {
  reason?: string;
  limit?: "server" | "account";
}

export function serverFullText(notice: ServerFullNotice | undefined): string {
  return notice?.limit === "account" ? ui.socket.tooManyTabsOpen : ui.socket.sketchyIsFullRightNow;
}
