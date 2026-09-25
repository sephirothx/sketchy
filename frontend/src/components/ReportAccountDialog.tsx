import { useState } from "react";

import { ReportDialog, type ReportReasonChoice } from "./ReportDialog";
import { submitPlayerReport, type ReportReason } from "../lib/moderation";
import { ui } from "../content/ui/index.ts";
import { isUploadedPicture } from "../lib/avatarDoodles";

/** Report what an account itself carries: its name, or its picture.

The other two report dialogs are about something that was *said* - a seat at a
table, a line in the lobby - and both cite evidence the server picks. A name
and a picture are neither: they belong to the account, they are on every lobby
row and on the profile page, and they are visible to people who have never
been in a room with their owner. That is why this exists; until now both could
only be reported from inside a room, which is the one place they are least
likely to be met (R-AVA-06).

Nothing is cited, because there is nothing said to cite. For a picture the
server reads which one is on the account and records it, so a reviewer is told
when it has changed rather than shown a different one without comment
(R-AVA-07).

The picture is offered as a reason only when there is one: the server refuses
a complaint about a picture that does not exist, and an option that leads
somewhere refused is worse than one that is absent. A name is always there, so
it is always offered - and when it is the only reason, the dialog says so
rather than presenting a choice of one. */
export function ReportAccountDialog({
  userId,
  displayName,
  avatarUrl,
  onClose,
}: {
  userId: string;
  displayName: string;
  /** Null when the account carries no picture, which decides whether the
      picture can be complained about at all. */
  avatarUrl: string | null;
  onClose: () => void;
}) {
  const reasons: ReportReasonChoice<ReportReason>[] = [
    { value: "inappropriate_name", label: ui.reportAccountDialog.inappropriateName },
    // A doodle is our drawing rather than something the player put up, so
    // it is no more a picture to complain about than no picture (R-AVA-09).
    ...(isUploadedPicture(avatarUrl)
      ? [{ value: "inappropriate_avatar" as ReportReason, label: ui.reportAccountDialog.inappropriatePicture }]
      : []),
  ];
  const [reason, setReason] = useState<ReportReason>(reasons[0].value);

  return (
    <ReportDialog
      title={ui.reportAccountDialog.reportDisplayName({ displayName })}
      intro={ui.reportAccountDialog.nothingHappensYet({ name: displayName })}
      testId="report-account-dialog"
      // Shown only while it is what the complaint is about: a picture beside
      // a complaint about a name is the wrong evidence in front of the person
      // choosing.
      quoted={
        avatarUrl && reason === "inappropriate_avatar" && (
          <figure className="report-quoted-picture" data-testid="report-quoted-picture">
            <img src={avatarUrl} alt={ui.reportAccountDialog.theirPicture({ name: displayName })} />
          </figure>
        )
      }
      reason={{
        label: ui.reportAccountDialog.whatWrongWith,
        choices: reasons,
        value: reason,
        onChange: setReason,
        // An account with no picture can only be reported for its name.
        onlyChoice: ui.reportAccountDialog.reportedTheirNameTheyHaveNo,
      }}
      attachedHint={
        reason === "inappropriate_avatar"
          ? ui.reportAccountDialog.thePictureOnTheAccount
          : ui.reportAccountDialog.theNameOnTheAccount
      }
      onSend={async (details) => {
        await submitPlayerReport({ reportedUserId: userId, reason, details });
        return ui.reportAccountDialog.sentWithWhatAboutAttached;
      }}
      onClose={onClose}
    />
  );
}
