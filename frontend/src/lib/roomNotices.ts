/** Why a seat was taken away, in the reader's language.

`kicked` and `session_superseded` arrive with a `code` and an English
`reason`. The reason is for a log and a person reading the wire by hand; the
sentence is written here, from the code, like every refusal (R-I18N-01). An
unknown code - a newer server - gets the general sentence rather than the
server's English. */
import { ui } from "../content/ui/index.ts";

export function kickedText(code: unknown): string {
  switch (code) {
    case "kicked_by_vote":
      return ui.roomNotices.kickedByVote;
    case "room_closed":
      return ui.roomNotices.roomClosed;
    case "removed_by_admin":
      return ui.roomNotices.removedByAdmin;
    default:
      return ui.activeGameRoom.youWereKickedFromThe;
  }
}

export function supersededText(code: unknown): string {
  switch (code) {
    case "account_deleted":
      return ui.roomNotices.accountDeleted;
    case "account_suspended":
      return ui.roomNotices.accountSuspended;
    default:
      // `opened_elsewhere`, and anything newer.
      return ui.activeGameRoom.thisRoomWasOpenedIn;
  }
}
