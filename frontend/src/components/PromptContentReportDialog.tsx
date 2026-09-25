import { useId, useState } from "react";
import { ReportDialog } from "./ReportDialog";
import {
  submitPromptContentReport,
  type PromptContentReportReason,
} from "../lib/promptLists";
import type { CommunityPromptListDetail } from "../types";
import { ui } from "../content/ui/index.ts";

const REASONS: Array<{ value: PromptContentReportReason; label: string }> = [
  { value: "inappropriate", get label() { return ui.promptContentReportDialog.inappropriateContent; } },
  { value: "hateful_or_abusive", get label() { return ui.promptContentReportDialog.hatefulOrAbusiveContent; } },
  { value: "sexual_content", get label() { return ui.promptContentReportDialog.sexualContent; } },
  { value: "violence", get label() { return ui.promptContentReportDialog.violence; } },
  { value: "spam", get label() { return ui.promptContentReportDialog.spam; } },
  { value: "other", get label() { return ui.promptContentReportDialog.other; } },
];

interface PromptContentReportDialogProps {
  /** Enough of a list to report it: the target, and the prompts to name one.
      Only a published list can be reported: nobody else can see a private one. */
  promptList: Pick<CommunityPromptListDetail, "id" | "name" | "prompts">;
  onClose: () => void;
}

/** Report a published prompt list, or one prompt in it (R-MOD-09).

The same dialog as every other report, with one field more: which part of the
list the complaint is about. The words are optional here as everywhere - the
server snapshots the list's name or the prompt's text with the report, and
that snapshot is the evidence. */
export function PromptContentReportDialog({
  promptList,
  onClose,
}: PromptContentReportDialogProps) {
  const targetId = useId();
  const [target, setTarget] = useState("list");
  const [reason, setReason] = useState<PromptContentReportReason>("inappropriate");

  return (
    <ReportDialog
      title={ui.promptContentReportDialog.reportList({ name: promptList.name })}
      intro={ui.promptContentReportDialog.reportsAreReviewedAfterSubmissionList}
      testId="prompt-content-report-dialog"
      reason={{
        label: ui.promptContentReportDialog.reason,
        choices: REASONS,
        value: reason,
        onChange: setReason,
      }}
      extraFields={
        <>
          <label htmlFor={targetId}>{ui.promptContentReportDialog.content}</label>
          <select id={targetId} value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="list">{ui.promptContentReportDialog.entireList}</option>
            {promptList.prompts.map((prompt) => (
              <option key={prompt.promptVersionId} value={prompt.promptVersionId}>
                {prompt.prompt}
              </option>
            ))}
          </select>
        </>
      }
      onSend={async (details) => {
        await submitPromptContentReport({
          promptListId: promptList.id,
          promptVersionId: target === "list" ? undefined : target,
          reason,
          details,
        });
        return ui.promptContentReportDialog.sentWithTheListAttached;
      }}
      onClose={onClose}
    />
  );
}
