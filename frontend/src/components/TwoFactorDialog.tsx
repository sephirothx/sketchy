import { Suspense, lazy, useEffect, useId, useRef, useState } from "react";

// Split out so the QR encoder is fetched when somebody actually enrols.
const AuthenticatorQrCode = lazy(() => import("./AuthenticatorQrCode"));
import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { downloadRecoveryCodes } from "../lib/recoveryCodeFile";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import {
  beginEnrolment,
  confirmEnrolment,
  fetchSecondFactor,
  removeSecondFactor,
  replaceRecoveryCodes,
  type EnrolmentOffer,
  type SecondFactorState,
} from "../lib/secondFactor";

/**
 * Setting up the second factor an account can hold, and a staff account must.
 *
 * Enrolment is two steps because the server stores nothing until a code proves
 * the secret arrived (R-AUTH-20): the offer lives in this component's state and
 * is sent back with the first code. An enrolment somebody starts and abandons
 * therefore leaves no credential behind, and cannot lock them out.
 *
 * The recovery codes appear once. There is no second chance to read them
 * because the server keeps only hashes, exactly as it does for session tokens
 * — so this says so plainly before showing them, rather than letting somebody
 * close the dialog and discover it afterwards.
 */
export function TwoFactorDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const codeId = useId();
  const keyId = useId();

  const [state, setState] = useState<SecondFactorState | null>(null);
  const [offer, setOffer] = useState<EnrolmentOffer | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const { notify } = useToast();
  const username = useAuthStore((state) => state.user?.displayName ?? "account");

  useFocusTrap(dialogRef, { active: true, onEscape: onClose });

  async function copy(value: string, what: string) {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      notify(`${what} copied.`, "success", 2500);
    } catch {
      notify(`Couldn't copy the ${what.toLowerCase()}. Select it and copy by hand.`, "error");
    }
  }

  useEffect(() => {
    let active = true;
    void fetchSecondFactor()
      .then((result) => { if (active) setState(result); })
      .catch(() => { if (active) setError("Could not read your security settings."); });
    return () => { active = false; };
  }, []);

  function failed(problem: unknown, fallback: string) {
    setError(problem instanceof ApiError ? problem.message : fallback);
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setOffer(await beginEnrolment());
    } catch (problem) {
      failed(problem, "Could not start setting this up.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    if (!offer || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await confirmEnrolment(offer.secret, code, password);
      setCodes(result.recoveryCodes);
      setOffer(null);
      setCode("");
      setState(await fetchSecondFactor());
    } catch (problem) {
      failed(problem, "That code was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function newCodes() {
    setBusy(true);
    setError(null);
    try {
      setCodes((await replaceRecoveryCodes(password)).recoveryCodes);
      setPassword("");
      setState(await fetchSecondFactor());
    } catch (problem) {
      failed(problem, "Could not replace your recovery codes.");
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    setError(null);
    try {
      await removeSecondFactor(password);
      setPassword("");
      setCodes(null);
      setState(await fetchSecondFactor());
    } catch (problem) {
      failed(problem, "Could not turn this off.");
    } finally {
      setBusy(false);
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
        className="modal-card two-factor"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <h3 id={titleId} className="modal-title">Two-factor authentication</h3>
        {error && <p className="auth-error" role="alert">{error}</p>}

        {codes && (
          <div className="two-factor-codes">
            <p className="modal-body">
              <strong>Save these recovery codes now.</strong> Each one signs you
              in once if you lose your authenticator app. They are not shown
              again — only their hashes are kept.
            </p>
            <ul aria-label="Recovery codes">
              {codes.map((value) => <li key={value}><code>{value}</code></li>)}
            </ul>
            <div className="two-factor-actions">
              <button
                type="button"
                className="btn btn-primary btn-compact"
                onClick={() => downloadRecoveryCodes(username, codes)}
              >
                Download as a file
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => void copy(codes.join("\n"), "Recovery codes")}
              >
                Copy all
              </button>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              onClick={() => setCodes(null)}
            >
              I have saved them
            </button>
          </div>
        )}

        {!codes && state && !state.enrolled && !offer && (
          <>
            <p className="modal-body">
              An authenticator app produces a six-digit code that changes every
              thirty seconds.{" "}
              {state.required ? (
                <>
                  This account's role requires one: it is asked for when you
                  sign in, and again before anything that suspends a player,
                  changes a role, or reconfigures the server.
                </>
              ) : (
                <>
                  Moderators and administrators must have one, and it has to be
                  set up before the role is granted — so this is the step to
                  take first if you are being given one. It does not change how
                  you sign in until then.
                </>
              )}
            </p>
            <button type="button" onClick={() => void start()} disabled={busy}>
              {busy ? "Setting up…" : "Set up"}
            </button>
          </>
        )}

        {!codes && offer && (
          <form onSubmit={(event) => void confirm(event)}>
            <p className="modal-body">
              Scan this with your authenticator app, then type the code it
              shows. Your password goes with it, so that nobody holding this
              browser's session alone can bind a second factor to the account.
            </p>
            <Suspense
              fallback={<p className="modal-hint">Drawing the code…</p>}
            >
              <AuthenticatorQrCode
                uri={offer.uri}
                label="Scan this with your authenticator app to add this account"
              />
            </Suspense>
            {/* The key is the fallback rather than the instruction: most
                people scan, and the ones who cannot - a desktop authenticator,
                a camera that will not focus - need it spelled out and
                copyable rather than hidden. */}
            {showKey ? (
              <div className="two-factor-secret-block">
                <p className="modal-hint" id={keyId}>
                  Type or paste this key into the app instead.
                </p>
                <p className="two-factor-secret">
                  <code>{offer.secret}</code>
                </p>
                <button
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => void copy(offer.secret, "Setup key")}
                >
                  Copy key
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-ghost btn-compact two-factor-reveal-key"
                onClick={() => setShowKey(true)}
              >
                Can't scan it? Enter a key instead
              </button>
            )}
            <label htmlFor={codeId}>Code from your app</label>
            <input
              id={codeId}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={16}
              // Six digits and there is nothing else to decide, so the form
              // does not make somebody reach for a button as well.
              onInput={(event) => {
                const digits = event.currentTarget.value.replace(/\D/g, "");
                if (digits.length === 6 && password) {
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              required
            />
            <label>
              Your password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? "Checking…" : "Confirm"}
            </button>
          </form>
        )}

        {!codes && state?.enrolled && (
          <>
            <p className="modal-body">
              Two-factor authentication is on. You have{" "}
              {state.recoveryCodesRemaining} recovery{" "}
              {state.recoveryCodesRemaining === 1 ? "code" : "codes"} left.
            </p>
            <label>
              Your password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
            </label>
            <div className="two-factor-actions">
              <button type="button" onClick={() => void newCodes()} disabled={busy || !password}>
                New recovery codes
              </button>
              {/*
                Offered even when the role requires it: the server refuses,
                and being told why by the thing you asked is clearer than an
                option that silently is not there.
              */}
              <button type="button" onClick={() => void turnOff()} disabled={busy || !password}>
                Turn off
              </button>
            </div>
          </>
        )}

        <button type="button" className="modal-dismiss" onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
