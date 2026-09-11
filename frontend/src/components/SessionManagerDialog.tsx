import { useClock } from "../hooks/useClock";
import { useEffect, useId, useRef, useState } from "react";
import { useFocusTrap } from "../hooks/useFocusTrap";
import {
  fetchAccountSessions,
  logoutEverywhere,
  revokeAccountSession,
  type AccountSession,
} from "../lib/sessions";
import { useAuthStore } from "../store/authStore";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

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
            refusalText(failure, ui.sessionManagerDialog.couldNotLoadSignedDevices),
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
      setError(refusalText(failure, ui.sessionManagerDialog.couldNotRevokeDevice));
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
      setError(refusalText(failure, ui.sessionManagerDialog.couldNotLogOutEverywhere));
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
        <h3 id={titleId} className="modal-title">{ui.sessionManagerDialog.signedDevices}</h3>
        <p className="modal-body">
          {ui.sessionManagerDialog.revokeAnyDeviceYouNoLonger}
        </p>
        {loading && <p role="status">{ui.sessionManagerDialog.loadingDevices}</p>}
        {error && <p className="auth-error" role="alert">{error}</p>}
        {!loading && (
          <ul className="session-list">
            {sessions.map((session) => (
              <li key={session.id}>
                <span>
                  <strong>{session.deviceLabel}</strong>
                  {session.current && <span className="session-current">{ui.sessionManagerDialog.currentDevice}</span>}
                  <small>{ui.sessionManagerDialog.lastUsed({ when: usedLabel(session.lastUsedAt, dateTime) })}</small>
                  {session.idleExpiresAt && (
                    <small>
                      {ui.sessionManagerDialog.signsOutOn({
                        when: usedLabel(session.idleExpiresAt, dateTime),
                      })}
                    </small>
                  )}
                  {/*
                    Worth interrupting for: a session used from a browser it
                    was not issued to is the shape a stolen cookie has. Says
                    only that it happened and when - the server keeps a hash
                    of the address, not the address.
                  */}
                  {session.anomalyAt && (
                    <small className="session-anomaly" role="note">
                      {ui.sessionManagerDialog.usedElsewhere({
                        when: usedLabel(session.anomalyAt, dateTime),
                      })}
                    </small>
                  )}
                </span>
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => void revoke(session)}
                >
                  {busyId === session.id ? ui.sessionManagerDialog.revoking : ui.sessionManagerDialog.revoke}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="session-actions">
          <button type="button" onClick={onClose} disabled={busyId !== null}>{ui.sessionManagerDialog.close}</button>
          <button
            type="button"
            className="session-revoke-all"
            onClick={() => void revokeAll()}
            disabled={busyId !== null || sessions.length === 0}
          >
            {busyId === "all" ? ui.sessionManagerDialog.loggingOut : ui.sessionManagerDialog.logOutEverywhere}
          </button>
        </div>
      </div>
    </div>
  );
}
