import { useClock } from "../hooks/useClock";
import { useEffect, useState } from "react";
import { ModalShell } from "./ui/ModalShell";
import { ConfirmationDialog } from "./ConfirmationDialog";
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
  const logout = useAuthStore((state) => state.logout);
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);

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

  const dismiss = () => {
    if (busyId === null) onClose();
  };

  return (
    <>
      <ModalShell
        title={ui.sessionManagerDialog.signedDevices}
        cardClassName="session-manager"
        onDismiss={dismiss}
        footer={
          <button
            type="button"
            className="btn btn-danger session-revoke-all"
            onClick={() => setConfirmingAll(true)}
            disabled={busyId !== null || sessions.length === 0}
          >
            {busyId === "all" ? ui.sessionManagerDialog.loggingOut : ui.sessionManagerDialog.logOutEverywhere}
          </button>
        }
      >
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
                  className="btn btn-secondary btn-compact"
                  disabled={busyId !== null}
                  onClick={() => void revoke(session)}
                >
                  {busyId === session.id ? ui.sessionManagerDialog.revoking : ui.sessionManagerDialog.revoke}
                </button>
              </li>
            ))}
          </ul>
        )}
      </ModalShell>
      {/* Asked first, because it reaches further than it reads: "everywhere"
          includes this device, which is signed out along with the rest. A
          single revoke says which device it means; this one does not. */}
      {confirmingAll && (
        <ConfirmationDialog
          title={ui.sessionManagerDialog.logOutEverywhereTitle}
          description={ui.sessionManagerDialog.logOutEverywhereBody}
          confirmLabel={ui.sessionManagerDialog.logOutEverywhere}
          onCancel={() => setConfirmingAll(false)}
          onConfirm={() => {
            setConfirmingAll(false);
            void revokeAll();
          }}
        />
      )}
    </>
  );
}
