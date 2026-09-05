import { useClock } from "../hooks/useClock";
import { useEffect, useId, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import {
  exportFailureNote,
  exportLabel,
  fetchDataExports,
  pollDelayMs,
  requestDataExport,
  type DataExportJob,
} from "../lib/accountData";
import { ApiError } from "../lib/api";

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
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const { dateTime, date } = useClock();
  const [exports, setExports] = useState<DataExportJob[]>([]);
  const [nextRequestAt, setNextRequestAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useFocusTrap(dialogRef, { active: true, onEscape: onClose });

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
            failure instanceof ApiError
              ? failure.message
              : "Could not load your data exports.",
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
        failure instanceof ApiError
          ? failure.message
          : "Could not request your data export.",
      );
    } finally {
      setRequesting(false);
    }
  }

  // The server sends a date only while one is in the future, and none while
  // a job is merely live - the list already shows that one being prepared.
  const waitUntil = nextRequestAt ? new Date(nextRequestAt) : null;
  const canRequest = !loading && !requesting && !hasWork && !waitUntil;

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card account-data-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">Your data</h3>
        <p className="modal-body">
          Download a private JSON copy of your account and gameplay data. Other players’ profiles and messages are not included.
        </p>
        {error && <p className="auth-error" role="alert">{error}</p>}

        <section className="account-data-section" aria-labelledby={`${titleId}-exports`}>
          <div className="account-data-heading-row">
            <h4 id={`${titleId}-exports`}>Data exports</h4>
            <button type="button" onClick={() => void startExport()} disabled={!canRequest}>
              {requesting ? "Requesting…" : "Request export"}
            </button>
          </div>
          {loading && <p role="status">Loading exports…</p>}
          {!loading && exports.length === 0 && (
            <p className="account-data-empty">You have not requested an export yet.</p>
          )}
          {exports.length > 0 && (
            <ul className="account-export-list">
              {exports.map((job) => (
                <li key={job.id}>
                  <span>
                    <strong>{exportLabel(job)}</strong>
                    <small>
                      Requested {dateLabel(job.createdAt, dateTime)} · format v{job.schemaVersion}
                    </small>
                    {exportFailureNote(job) && (
                      <small className="account-export-note">{exportFailureNote(job)}</small>
                    )}
                  </span>
                  {job.downloadUrl && (
                    <a href={job.downloadUrl} download>Download</a>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="account-data-note">
            One export a week; ready exports expire after seven days.
            {waitUntil && ` You can request another on ${date(waitUntil)}.`}
          </p>
        </section>

        <div className="account-data-actions">
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
