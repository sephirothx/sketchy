import { useEffect, useId, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import {
  deleteAccount,
  fetchDataExports,
  requestDataExport,
  type DataExportJob,
} from "../lib/accountData";
import { ApiError } from "../lib/api";
import { useAuthStore } from "../store/authStore";

function dateLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}

function exportLabel(job: DataExportJob): string {
  if (job.status === "pending") return "Queued";
  if (job.status === "processing") return "Preparing…";
  if (job.status === "ready") return "Ready";
  return "Could not prepare";
}

export function AccountDataDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const [exports, setExports] = useState<DataExportJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [requesting, setRequesting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useFocusTrap(dialogRef, { active: true, onEscape: onClose });

  useEffect(() => {
    let active = true;
    void fetchDataExports()
      .then((result) => {
        if (active) setExports(result.exports);
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
    const timer = window.setInterval(() => {
      void fetchDataExports()
        .then((result) => setExports(result.exports))
        .catch(() => {});
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [hasWork]);

  async function startExport() {
    setRequesting(true);
    setError(null);
    try {
      const job = await requestDataExport();
      setExports((items) => [job, ...items.filter((item) => item.id !== job.id)]);
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

  async function confirmDeletion(event: React.FormEvent) {
    event.preventDefault();
    if (confirmation !== "DELETE" || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteAccount(user?.isAnonymous ? undefined : password);
      onClose();
      // This also releases any live seat, provisions a clean guest, and
      // reconnects the socket under the replacement identity.
      await logout();
    } catch (failure) {
      setError(
        failure instanceof ApiError ? failure.message : "Could not delete the account.",
      );
      setDeleting(false);
    }
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deleting) onClose();
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
            <button type="button" onClick={() => void startExport()} disabled={requesting}>
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
                      Requested {dateLabel(job.createdAt)} · format v{job.schemaVersion}
                    </small>
                  </span>
                  {job.downloadUrl && (
                    <a href={job.downloadUrl} download>Download</a>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="account-data-note">Ready exports expire after seven days.</p>
        </section>

        <section className="account-data-section account-danger-zone" aria-labelledby={`${titleId}-delete`}>
          <h4 id={`${titleId}-delete`}>Delete account</h4>
          <p>
            Your identity and name are removed from saved games. Shared scores and game structure remain as “Deleted player.” This cannot be undone.
          </p>
          {!showDelete ? (
            <button type="button" className="account-delete-start" onClick={() => setShowDelete(true)}>
              Delete account…
            </button>
          ) : (
            <form className="account-delete-form" onSubmit={(event) => void confirmDeletion(event)}>
              {!user?.isAnonymous && (
                <label>
                  Password
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                </label>
              )}
              <label>
                Type DELETE to confirm
                <input
                  type="text"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  autoComplete="off"
                  required
                />
              </label>
              <div className="account-delete-actions">
                <button
                  type="button"
                  onClick={() => {
                    setShowDelete(false);
                    setConfirmation("");
                    setPassword("");
                  }}
                  disabled={deleting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="account-delete-confirm"
                  disabled={confirmation !== "DELETE" || deleting}
                >
                  {deleting ? "Deleting…" : "Permanently delete"}
                </button>
              </div>
            </form>
          )}
        </section>

        <div className="account-data-actions">
          <button type="button" onClick={onClose} disabled={deleting}>Close</button>
        </div>
      </div>
    </div>
  );
}
