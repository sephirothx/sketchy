import { useClock } from "../hooks/useClock";
import { useEffect, useId, useState } from "react";
import { ModalShell } from "./ui/ModalShell";
import {
  exportFailureNote,
  exportLabel,
  fetchDataExports,
  pollDelayMs,
  requestDataExport,
  type DataExportJob,
} from "../lib/accountData";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

function dateLabel(value: string, dateTime: (date: Date) => string): string {
  return dateTime(new Date(value));
}

/**
 * Requesting and downloading a copy of everything Sketchy holds about you
 * (R-PRIV-01). One a week (R-PRIV-12): building one walks every game the
 * account played, so the button says when the next is allowed rather than
 * offering a request the server will refuse. Deleting the account used to
 * live at the bottom of this dialog, which is where an irreversible act is
 * least expected; it has a row and a dialog of its own in Settings now.
 */
export function AccountDataDialog({ onClose }: { onClose: () => void }) {
  const sectionId = useId();
  const { dateTime, date } = useClock();
  const [exports, setExports] = useState<DataExportJob[]>([]);
  const [nextRequestAt, setNextRequestAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchDataExports()
      .then((result) => {
        if (!active) return;
        setExports(result.exports);
        setNextRequestAt(result.nextRequestAt);
      })
      .catch((failure) => {
        if (active) {
          setError(
            refusalText(failure, ui.accountDataDialog.couldNotLoadYourDataExports),
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const hasWork = exports.some((job) => job.status === "pending" || job.status === "processing");
  useEffect(() => {
    if (!hasWork) return;
    // One build at a time on the server, so a queued job can sit behind
    // another account's: poll briskly while that is unlikely, then settle.
    const startedAt = Date.now();
    let timer = 0;
    let active = true;
    const tick = () => {
      void fetchDataExports()
        .then((result) => {
          if (!active) return;
          setExports(result.exports);
          setNextRequestAt(result.nextRequestAt);
        })
        .catch(() => {})
        .finally(() => {
          if (active) timer = window.setTimeout(tick, pollDelayMs(Date.now() - startedAt));
        });
    };
    timer = window.setTimeout(tick, pollDelayMs(0));
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [hasWork]);

  async function startExport() {
    setRequesting(true);
    setError(null);
    try {
      const job = await requestDataExport();
      setExports((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      const refreshed = await fetchDataExports().catch(() => null);
      if (refreshed) setNextRequestAt(refreshed.nextRequestAt);
    } catch (failure) {
      setError(
        refusalText(failure, ui.accountDataDialog.couldNotRequestYourDataExport),
      );
    } finally {
      setRequesting(false);
    }
  }

  // The server sends a date only while one is in the future, and none while
  // a job is merely live - the list already shows that one being prepared.
  const waitUntil = nextRequestAt ? new Date(nextRequestAt) : null;
  const canRequest = !loading && !requesting && !hasWork && !waitUntil;

  // Only information and one action of its own, which sits beside the list
  // it adds to: the ✕ is the way out, so the footer has nothing to hold.
  return (
    <ModalShell
      title={ui.accountDataDialog.yourData}
      cardClassName="account-data-dialog"
      onDismiss={onClose}
    >
      <p className="modal-body">
        {ui.accountDataDialog.downloadPrivateJsonCopyYourAccount}
      </p>
      {error && <p className="auth-error" role="alert">{error}</p>}

      <section className="account-data-section" aria-labelledby={`${sectionId}-exports`}>
        <div className="account-data-heading-row">
          <h3 id={`${sectionId}-exports`}>{ui.accountDataDialog.dataExports}</h3>
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            onClick={() => void startExport()}
            disabled={!canRequest}
          >
            {requesting ? ui.accountDataDialog.requesting : ui.accountDataDialog.requestExport}
          </button>
        </div>
        {loading && <p role="status">{ui.accountDataDialog.loadingExports}</p>}
        {!loading && exports.length === 0 && (
          <p className="account-data-empty">{ui.accountDataDialog.youHaveNotRequestedExportYet}</p>
        )}
        {exports.length > 0 && (
          <ul className="account-export-list">
            {exports.map((job) => (
              <li key={job.id}>
                <span>
                  <strong>{exportLabel(job)}</strong>
                  <small>
                    {ui.accountDataDialog.requestedOn({
                      when: dateLabel(job.createdAt, dateTime),
                      schemaVersion: job.schemaVersion,
                    })}
                  </small>
                  {exportFailureNote(job) && (
                    <small className="account-export-note">{exportFailureNote(job)}</small>
                  )}
                </span>
                {job.downloadUrl && (
                  <a className="btn btn-primary btn-compact" href={job.downloadUrl} download>
                    {ui.accountDataDialog.download}
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="account-data-note">
          {ui.accountDataDialog.exportAllowance({
            nextAllowed: waitUntil ? date(waitUntil) : null,
          })}
        </p>
      </section>
    </ModalShell>
  );
}
