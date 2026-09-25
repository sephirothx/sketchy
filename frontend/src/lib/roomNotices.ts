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
      return ui.roomNotices.kickedByAdmin;
    default:
      return ui.activeGameRoom.youWereKickedFromThe;
  }
}

/** Whether a `kicked` event was a kick - by a vote or an administrator -
rather than the room closing under the player, which is not one. The lobby's
notice is titled by it; an unknown code is taken as a kick, the same general
case `kickedText` falls back to. */
export function isKick(code: unknown): boolean {
  return code !== "room_closed";
}

export function supersededText(code: unknown): string {
  switch (code) {
    case "account_deleted":
      return ui.roomNotices.accountDeleted;
    case "account_suspended":
      return ui.roomNotices.accountSuspended;
    case "signed_out":
      return ui.roomNotices.signedOut;
    default:
      // `opened_elsewhere`, and anything newer.
      return ui.activeGameRoom.thisRoomWasOpenedIn;
  }
}
