import { useEffect, useState } from "react";
import { useClock } from "../hooks/useClock";
import { ConfirmationDialog } from "./ConfirmationDialog";
import { SettingsRow } from "./SettingsRow";
import {
  fetchAccountSessions,
  logoutEverywhere,
  revokeAccountSession,
  type AccountSession,
} from "../lib/sessions";
import { useAuthStore } from "../store/authStore";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

/**
 * Settings → Account → Signed-in devices: every browser holding a session on
 * the account, each with a way to end it (R-AUTH-03, R-AUTH-22).
 *
 * In the page rather than behind a *Manage* dialog (#864). The list is short
 * and is the whole point of the row; a dialog over Settings, which is itself
 * over a room, was a third layer for something worth reading at a glance -
 * a device used from a browser it was not issued to most of all.
 */
export function SignedInDevices() {
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
          setError(refusalText(failure, ui.signedInDevices.couldNotLoadSignedDevices));
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
        // This browser's own session: the server has already ended it, so
        // the client follows rather than showing a list it can no longer read.
        await logout();
        return;
      }
      setSessions((items) => items.filter((item) => item.id !== session.id));
    } catch (failure) {
      setError(refusalText(failure, ui.signedInDevices.couldNotRevokeDevice));
    } finally {
      setBusyId(null);
    }
  }

  async function revokeAll() {
    setBusyId("all");
    setError(null);
    try {
      await logoutEverywhere();
      await logout();
    } catch (failure) {
      setError(refusalText(failure, ui.signedInDevices.couldNotSignOutEverywhere));
      setBusyId(null);
    }
  }

  return (
    <>
      <SettingsRow
        label={ui.settingsOverlay.signedDevices}
        hint={ui.signedInDevices.revokeAnyDeviceYouNoLonger}
      >
        <button
          type="button"
          className="btn btn-danger-ghost btn-compact"
          onClick={() => setConfirmingAll(true)}
          disabled={busyId !== null || sessions.length === 0}
        >
          {busyId === "all" ? ui.signedInDevices.signingOut : ui.signedInDevices.signOutEverywhere}
        </button>
      </SettingsRow>
      {loading && <p className="settings-row-note" role="status">{ui.signedInDevices.loadingDevices}</p>}
      {error && <p className="auth-error" role="alert">{error}</p>}
      {!loading && sessions.length > 0 && (
        <ul className="session-list" aria-label={ui.settingsOverlay.signedDevices}>
          {sessions.map((session) => (
            <li key={session.id}>
              <span>
                <strong>{session.deviceLabel}</strong>
                {session.current && <span className="session-current">{ui.signedInDevices.currentDevice}</span>}
                <small>{ui.signedInDevices.lastUsed({ when: dateTime(new Date(session.lastUsedAt)) })}</small>
                {session.idleExpiresAt && (
                  <small>
                    {ui.signedInDevices.signsOutOn({ when: dateTime(new Date(session.idleExpiresAt)) })}
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
                    {ui.signedInDevices.usedElsewhere({ when: dateTime(new Date(session.anomalyAt)) })}
                  </small>
                )}
              </span>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                disabled={busyId !== null}
                onClick={() => void revoke(session)}
              >
                {busyId === session.id ? ui.signedInDevices.revoking : ui.signedInDevices.revoke}
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* Asked first, because it reaches further than it reads: "everywhere"
          includes this device, which is signed out along with the rest. A
          single revoke says which device it means; this one does not. */}
      {confirmingAll && (
        <ConfirmationDialog
          title={ui.signedInDevices.logOutEverywhereTitle}
          description={ui.signedInDevices.logOutEverywhereBody}
          confirmLabel={ui.signedInDevices.signOutEverywhere}
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
