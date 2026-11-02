import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AppHeader } from "../components/AppHeader";
import { ui } from "../content/ui/index.ts";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { formatDate } from "../lib/clock";
import { refusalText } from "../lib/refusals";
import { cancelRenewal, requestCancellation } from "../lib/support";
import { useAuthStore } from "../store/authStore";
import { useSupportStore } from "../store/supportStore";
import { NotFoundPage } from "./NotFoundPage";
import "../styles/lazy/support.css";

function SignedIn() {
  const status = useSupportStore((state) => state.status);
  const refresh = useSupportStore((state) => state.refresh);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refresh().finally(() => setLoaded(true));
  }, [refresh]);

  const until = status?.until ? formatDate(new Date(status.until)) : "";
  if (!loaded) return null;
  if (done) return <p role="status">{ui.support.cancelDone({ date: until })}</p>;
  if (!status?.renews) return <p>{ui.support.cancelNothing}</p>;
  return (
    <>
      <p>{ui.support.cancelBody({ date: until })}</p>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      <button
        type="button"
        className="btn btn-danger"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          void cancelRenewal()
            .then(() => {
              setDone(true);
              return refresh();
            })
            .catch((failure) => setError(refusalText(failure, ui.support.cancelFailed)))
            .finally(() => setBusy(false));
        }}
      >
        {ui.support.cancelRenewal}
      </button>
    </>
  );
}

function SignedOut() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    void requestCancellation(email)
      .then(() => setDone(true))
      .catch((failure) => setError(refusalText(failure, ui.support.cancelFailed)))
      .finally(() => setBusy(false));
  };

  if (done) return <p role="status">{ui.support.cancelRequested}</p>;
  return (
    <form onSubmit={submit} className="support-cancel-form">
      <p>{ui.support.cancelSignedOut}</p>
      <label>
        {ui.support.cancelEmail}
        <input
          className="input-field"
          type="email"
          autoComplete="email"
          required
          maxLength={254}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="btn btn-danger" disabled={busy || !email.trim()}>
        {ui.support.cancelRenewal}
      </button>
    </form>
  );
}

/** Stopping a renewal on this site (R-SUP-09, Germany's §312k): one click signed
in, no login signed out. */
export function SupportCancelPage() {
  useDocumentTitle(ui.support.cancelTitle);
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const registered = Boolean(user && !user.isAnonymous);
  const plans = useSupportStore((state) => state.plans);
  const loadPlans = useSupportStore((state) => state.loadPlans);
  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);
  // Nothing here on a deployment that sells nothing (R-SUP-08).
  if (plans === null) return <NotFoundPage />;
  return (
    <div className="support-page">
      <AppHeader />
      <main className="surface-card support-page-card" data-testid="support-cancel">
        <h1>{ui.support.cancelTitle}</h1>
        {hasResolved && (registered ? <SignedIn /> : <SignedOut />)}
        <Link to="/">{ui.support.backToLobby}</Link>
      </main>
    </div>
  );
}
