import { useId, useRef, useState, type FormEvent } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import {
  submitPromptContentReport,
  type PromptContentReportReason,
} from "../lib/promptLists";
import type { SharedPromptList } from "../types";

const REASONS: Array<{ value: PromptContentReportReason; label: string }> = [
  { value: "inappropriate", label: "Inappropriate content" },
  { value: "hateful_or_abusive", label: "Hateful or abusive content" },
  { value: "sexual_content", label: "Sexual content" },
  { value: "violence", label: "Violence" },
  { value: "spam", label: "Spam" },
  { value: "other", label: "Other" },
];

interface PromptContentReportDialogProps {
  promptList: SharedPromptList;
  shareCode: string;
  onClose: () => void;
  onSubmitted: () => void;
}

export function PromptContentReportDialog({
  promptList,
  shareCode,
  onClose,
  onSubmitted,
}: PromptContentReportDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const targetId = useId();
  const reasonId = useId();
  const detailsId = useId();
  const [target, setTarget] = useState("list");
  const [reason, setReason] = useState<PromptContentReportReason>("inappropriate");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useFocusTrap(dialogRef, { onEscape: onClose, initialFocusRef: cancelRef });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !details.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await submitPromptContentReport({
        promptListId: promptList.id,
        promptVersionId: target === "list" ? undefined : target,
        shareCode,
        reason,
        details: details.trim(),
      });
      onSubmitted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send the report.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-overlay" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <div ref={dialogRef} className="modal-card prompt-content-report-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <h2 id={titleId} className="modal-title">Report {promptList.name}</h2>
      <p className="modal-body">Reports are reviewed after submission. The list stays available unless a moderator hides it.</p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor={targetId}>Content</label>
          <select id={targetId} value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="list">Entire list</option>
            {promptList.prompts.map((prompt) => <option key={prompt.promptVersionId} value={prompt.promptVersionId}>{prompt.prompt}</option>)}
          </select>
        <label htmlFor={reasonId}>Reason</label>
          <select id={reasonId} value={reason} onChange={(event) => setReason(event.target.value as PromptContentReportReason)}>
            {REASONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        <label htmlFor={detailsId}>What should the moderator know?</label>
          <textarea id={detailsId} value={details} required minLength={1} maxLength={2000} onChange={(event) => setDetails(event.target.value)} />
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="confirmation-dialog-actions">
          <button ref={cancelRef} type="button" className="confirmation-cancel-button" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="confirmation-danger-button" disabled={busy || !details.trim()}>{busy ? "Sending…" : "Send report"}</button>
        </div>
      </form>
    </div>
  </div>;
}
