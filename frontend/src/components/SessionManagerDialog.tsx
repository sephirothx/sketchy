import { useClock } from "../hooks/useClock";
import { useEffect, useId, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import {
  fetchAccountSessions,
  logoutEverywhere,
  revokeAccountSession,
  type AccountSession,
} from "../lib/sessions";
import { useAuthStore } from "../store/authStore";

function usedLabel(value: string, dateTime: (date: Date) => string): string {
  return dateTime(new Date(value));
}

export function SessionManagerDialog({ onClose }: { onClose: () => void }) {
  const { dateTime } = useClock();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const logout = useAuthStore((state) => state.logout);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusTrap(dialogRef, { active: true, onEscape: onClose });

  useEffect(() => {
    let active = true;
    void fetchAccountSessions()
      .then((result) => {
        if (active) setSessions(result.sessions);
      })
      .catch((failure) => {
        if (active) {
          setError(
            failure instanceof ApiError
              ? failure.message
              : "Could not load signed-in devices.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  async function revoke(session: AccountSession) {
    setBusyId(session.id);
    setError(null);
    try {
      await revokeAccountSession(session.id);
      if (session.current) {
        onClose();
        await logout();
        return;
      }
      setSessions((items) => items.filter((item) => item.id !== session.id));
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Could not revoke device.");
    } finally {
      setBusyId(null);
    }
  }

  async function revokeAll() {
    setBusyId("all");
    setError(null);
    try {
      await logoutEverywhere();
      onClose();
      await logout();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Could not log out everywhere.");
      setBusyId(null);
    }
  }

  return (
    <div
      className="modal-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-card session-manager"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">Signed-in devices</h3>
        <p className="modal-body">
          Revoke any device you no longer recognize. Device names are coarse and do not store browser versions.
        </p>
        {loading && <p role="status">Loading devices…</p>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {!loading && (
          <ul className="session-list">
            {sessions.map((session) => (
              <li key={session.id}>
                <span>
                  <strong>{session.deviceLabel}</strong>
                  {session.current && <span className="session-current">Current device</span>}
                  <small>Last used {usedLabel(session.lastUsedAt, dateTime)}</small>
                </span>
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => void revoke(session)}
                >
                  {busyId === session.id ? "Revoking…" : "Revoke"}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="session-actions">
          <button type="button" onClick={onClose} disabled={busyId !== null}>Close</button>
          <button
            type="button"
            className="session-revoke-all"
            onClick={() => void revokeAll()}
            disabled={busyId !== null || sessions.length === 0}
          >
            {busyId === "all" ? "Logging out…" : "Log out everywhere"}
          </button>
        </div>
      </div>
    </div>
  );
}
