import { Suspense, lazy, useEffect, useId, useRef, useState } from "react";

// Split out so the QR encoder is fetched when somebody actually enrols.
const AuthenticatorQrCode = lazy(() => import("./AuthenticatorQrCode"));

import { useFocusTrap } from "../hooks/useFocusTrap";
import { ApiError } from "../lib/api";
import { downloadRecoveryCodes } from "../lib/recoveryCodeFile";
import { SegmentedCodeInput } from "./SegmentedCodeInput";
import { CopyIcon, DownloadIcon } from "./icons";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";
import { passkeysAvailable, registerPasskey, fetchPasskeys, forgetPasskey, type Passkey } from "../lib/passkeys";
import {
  beginEnrolment,
  confirmEnrolment,
  confirmSecondFactorOwner,
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
  const keyId = useId();
  const passwordId = useId();

  const [state, setState] = useState<SecondFactorState | null>(null);
  const [offer, setOffer] = useState<EnrolmentOffer | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [savedCodes, setSavedCodes] = useState(false);
  // The role this enrolment just started, when one was waiting on it. Also
  // means every session on the account has ended, including this one.
  const [granted, setGranted] = useState<string | null>(null);
  // Passkeys this account holds, and whether this browser can make one. The
  // dialog offers the app route to a device that cannot (R-AUTH-23).
  const [passkeys, setPasskeys] = useState<Passkey[] | null>(null);
  const canUsePasskeys = passkeysAvailable();
  // Either kind counts. An account whose only credential is a passkey has
  // nothing enrolled in `state`, and would otherwise be shown the setup
  // chooser it has already been through.
  const hasFactor = Boolean(state?.enrolled) || (passkeys?.length ?? 0) > 0;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { notify } = useToast();
  const username = useAuthStore((state) => state.user?.displayName ?? "account");

  // While the codes are up and unacknowledged there is no way out of the
  // dialog but the tick: escaping or clicking away would take them with it,
  // and they are shown exactly once.
  const held = Boolean(codes) && !savedCodes;
  const dismiss = () => { if (!held) onClose(); };
  useFocusTrap(dialogRef, { active: true, onEscape: dismiss });

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
    void fetchPasskeys()
      .then((result) => { if (active) setPasskeys(result.passkeys); })
      .catch(() => { if (active) setPasskeys([]); });
    void fetchSecondFactor()
      .then((result) => {
        if (!active) return;
        setState(result);
      })
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
    await submitWith(code);
  }

  /** Takes the code explicitly: the last digit typed has not reached state
      yet when the row itself asks to submit, so reading `code` there would
      send five digits and be refused. */
  async function submitWith(entered: string) {
    if (!offer || busy) return;
    if (entered.length < 6) return;
    // Both halves or neither: sending the code alone would bind a factor
    // nobody has vouched for, and a role waiting on this enrolment would go
    // on waiting with nothing to say why.
    if (!password) {
      setError("Your password confirms the authenticator is yours.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await confirmEnrolment(offer.secret, entered, password || undefined);
      setSavedCodes(false);
      setCodes(result.recoveryCodes);
      setGranted(result.roleGranted);
      // Nothing is waiting once this lands, whichever way it went: the offer
      // either became a role or had already lapsed, and both are cleared
      // server-side. Saying so here is what takes the reminder out of the
      // menu without a reload.
      useAuthStore.getState().applyPendingRole(null);
      setOffer(null);
      setCode("");
      setPassword("");
      // Only when the account is still signed in to be asked. Taking up a
      // role ends every session, so this read would be a 401 and the state it
      // wants is on the other side of signing back in.
      if (!result.roleGranted) setState(await fetchSecondFactor());
    } catch (problem) {
      failed(problem, "That code was not accepted.");
    } finally {
      setBusy(false);
    }
  }

  async function addPasskey() {
    if (!password) {
      setError("Your password confirms this passkey is yours.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await registerPasskey(password);
      setPassword("");
      setGranted(result.roleGranted);
      useAuthStore.getState().applyPendingRole(null);
      setPasskeys((current) => [...(current ?? []), result.passkey]);
      if (!result.roleGranted) {
        setState(await fetchSecondFactor());
        notify("Passkey added.", "success");
        onClose();
      }
    } catch (problem) {
      // The browser's own refusals arrive as DOMException - a cancelled
      // prompt, a device that will not do it - and read badly as-is.
      if (problem instanceof DOMException) {
        setError("That passkey was not created. You can try again.");
      } else {
        failed(problem, "Could not add that passkey.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function removePasskey(passkeyId: string) {
    if (!password) {
      setError("Your password is needed to remove a passkey.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await forgetPasskey(passkeyId, password);
      setPassword("");
      setPasskeys((current) => (current ?? []).filter((one) => one.id !== passkeyId));
    } catch (problem) {
      failed(problem, "Could not remove that passkey.");
    } finally {
      setBusy(false);
    }
  }

  async function proveOwner() {
    setBusy(true);
    setError(null);
    try {
      const result = await confirmSecondFactorOwner(password, code);
      setPassword("");
      setCode("");
      setGranted(result.roleGranted);
      if (result.roleGranted) return;
      setState(await fetchSecondFactor());
      notify("Confirmed. This account can now be given a staff role.", "success");
    } catch (problem) {
      setCode("");
      failed(problem, "Could not confirm it.");
    } finally {
      setBusy(false);
    }
  }

  async function newCodes() {
    setBusy(true);
    setError(null);
    try {
      // A fresh set is a fresh promise to have kept them.
      setSavedCodes(false);
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
        if (event.target === event.currentTarget) dismiss();
      }}
    >
      {/* Only the two-column setup and the block of codes need the extra
          room; the manage view is one password field, and is the width every
          other dialog with one is. */}
      <div
        ref={dialogRef}
        className={`modal-card two-factor${offer || codes ? " two-factor-wide" : ""}`}
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
                <DownloadIcon size={15} />
                Download as a file
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => void copy(codes.join("\n"), "Recovery codes")}
              >
                <CopyIcon size={15} />
                Copy all
              </button>
            </div>
            {/* A tick rather than a button, and the only way past: these exist
                for the moment the authenticator is gone, and that is a bad
                moment to discover they were skipped past. */}
            <label className="two-factor-ack">
              <input
                type="checkbox"
                checked={savedCodes}
                onChange={(event) => setSavedCodes(event.target.checked)}
              />
              I have saved these somewhere safe
            </label>
            {/* Done means done. Behind these codes is the manage view, which
                is a different errand - somebody who came here to set a factor
                up has finished, and would be handed a password field and a
                "Turn off" button for their trouble. It is one click away from
                the row they started at, marked "Manage", when they want it.
                A role that has just taken effect is the exception: that panel
                is the outcome of this ceremony, not a way of managing it. */}
            <button
              type="button"
              className="modal-button"
              onClick={() => (granted ? setCodes(null) : onClose())}
              disabled={!savedCodes}
            >
              Done
            </button>
          </div>
        )}

        {/* The first thing offered, and the reason the app route is now the
            fallback rather than the only way: a passkey cannot be read out
            over the phone, which is the one attack a code has no answer for
            (R-AUTH-23). Somebody on a device that cannot make one is not
            stuck - the app is still there, one line below. */}
        {!codes && !granted && !offer && passkeys !== null && !hasFactor && (
          <div className="auth-form two-factor-choose">
            <p className="modal-body">
              Moderators and administrators sign in with a passkey: your
              device confirms it is you — a fingerprint, your face, or its
              PIN — and nothing is typed that could be given away.
            </p>
            <label htmlFor={passwordId}>Your password</label>
            <input
              id={passwordId}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
            <p className="modal-hint">Confirms the passkey is being added by you.</p>
            <button
              type="button"
              className="modal-button"
              onClick={() => void addPasskey()}
              disabled={busy || !password || !canUsePasskeys}
            >
              {busy ? "Waiting for your device…" : "Set up a passkey"}
            </button>
            <p className="modal-hint two-factor-fallback">
              {canUsePasskeys
                ? "No passkey on this device? "
                : "This browser cannot make a passkey. "}
              <button type="button" className="auth-link" onClick={() => void start()}>
                Use an authenticator app instead
              </button>
            </p>
          </div>
        )}

        {!codes && !granted && offer && (
          <form className="two-factor-setup" onSubmit={(event) => void confirm(event)}>
            <p className="modal-body two-factor-lead">
              Scan the code with an authenticator app, then type the six digits
              it shows back.
            </p>
            <div className="two-factor-scan">
              <div className="two-factor-frame">
                <Suspense fallback={<p className="modal-hint">Drawing the code…</p>}>
                  <AuthenticatorQrCode
                    uri={offer.uri}
                    label="Scan this with your authenticator app to add this account"
                  />
                </Suspense>
              </div>
              <p className="modal-hint">Point your app at this.</p>
            </div>

            <div className="auth-form two-factor-entry">
              <label htmlFor={keyId}>Setup key</label>
              <div className="two-factor-secret">
                <code id={keyId}>{offer.secret}</code>
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  onClick={() => void copy(offer.secret, "Setup key")}
                  aria-label="Copy the setup key"
                >
                  <CopyIcon size={15} />
                </button>
              </div>
              <p className="modal-hint">Use this if you can’t scan.</p>

              <label className="two-factor-code-label" htmlFor={passwordId}>
                Your password
              </label>
              <input
                id={passwordId}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
              {/* Asked for here rather than later because of what it proves.
                  The code says an authenticator produced it; the password
                  says whose account it is being bound to, and a role is
                  granted on the pair (R-AUTH-20). */}
              <p className="modal-hint">Confirms the authenticator is yours.</p>

              <span className="two-factor-code-label">Code from your app</span>
              <SegmentedCodeInput
                value={code}
                onChange={setCode}
                onComplete={(complete) => void submitWith(complete)}
                label="Code from your authenticator app"
                autoFocus
                disabled={busy}
              />

            </div>
            <div className="two-factor-decide">
              <button
                type="submit"
                className="modal-button"
                disabled={busy || !password || code.length < 6}
              >
                {busy ? "Checking…" : "Confirm"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {!codes && granted && (
          <>
            <p className="modal-body">
              <strong>
                You are now {granted === "admin" ? "an administrator" : "a moderator"}.
              </strong>{" "}
              Two-factor authentication is on, and the role that was waiting
              for it has taken effect. Your other devices have been signed out;
              this one carries on, and each sign-in from here asks for a code.
            </p>
            <button
              type="button"
              className="modal-button"
              onClick={() => {
                // The role only reaches the menu when the account is read
                // again: this browser's session was replaced by the one the
                // server minted for the role it now holds.
                void useAuthStore.getState().fetchMe();
                onClose();
              }}
            >
              Done
            </button>
          </>
        )}

        {!codes && !granted && !offer && hasFactor && (
          <>
            <p className="modal-body">
              Two-factor authentication is on.{" "}
              {state?.enrolled && (
                <>
                  You have {state.recoveryCodesRemaining} recovery{" "}
                  {state.recoveryCodesRemaining === 1 ? "code" : "codes"} left.
                </>
              )}
              {state?.enrolled && !state.passwordProved && (
                <>
                  {" "}Before this account can be given a moderator or
                  administrator role, confirm that the authenticator is yours
                  with your password and a code from it.
                </>
              )}{" "}
              Each of the changes below swaps a credential, so each asks for
              your password.
            </p>
            {/* What this account can actually sign in with, listed like the
                signed-in devices are: several is the point, because losing
                one device should not be losing the role. */}
            {(passkeys?.length ?? 0) > 0 && (
              <ul className="two-factor-passkeys" aria-label="Passkeys">
                {(passkeys ?? []).map((passkey) => (
                  <li key={passkey.id}>
                    <span className="two-factor-passkey-name">
                      {passkey.label}
                      {!passkey.backedUp && (
                        <span className="modal-hint"> · on this device only</span>
                      )}
                    </span>
                    <button
                      type="button"
                      className="btn btn-danger-ghost btn-compact"
                      onClick={() => void removePasskey(passkey.id)}
                      disabled={busy || !password}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="auth-form two-factor-manage">
              <label htmlFor={passwordId}>Your password</label>
              <input
                id={passwordId}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
              />
              {/* Only while it matters: setting a factor up asks for no
                  password, so one may be in place that nobody has proved
                  belongs to this account — which is the one thing a staff
                  role needs of it (R-AUTH-20). Both halves are asked for
                  here: the password says the owner is present, the code says
                  the authenticator in place is theirs. */}
              {state?.enrolled && !state.passwordProved && (
                <>
                  <span className="two-factor-code-label">Code from your app</span>
                  <SegmentedCodeInput
                    value={code}
                    onChange={setCode}
                    label="Code from your authenticator app"
                    disabled={busy}
                  />
                  <button
                    type="button"
                    className="modal-button"
                    onClick={() => void proveOwner()}
                    disabled={busy || !password || code.length < 6}
                  >
                    Confirm it’s yours
                  </button>
                </>
              )}
              <div className="two-factor-actions">
                {canUsePasskeys && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-compact"
                    onClick={() => void addPasskey()}
                    disabled={busy || !password}
                  >
                    Add a passkey
                  </button>
                )}
                {/* Both of these are about the authenticator app, and an
                    account whose only credential is a passkey has none: the
                    endpoints answer 409, so offering them is offering a
                    refusal. What that account wants instead is the app it
                    does not have yet. */}
                {state?.enrolled ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-secondary btn-compact"
                      onClick={() => void newCodes()}
                      disabled={busy || !password}
                    >
                      New recovery codes
                    </button>
                    {/*
                      Offered even when the role requires it: the server
                      refuses, and being told why by the thing you asked is
                      clearer than an option that silently is not there.
                    */}
                    <button
                      type="button"
                      className="btn btn-danger-ghost btn-compact"
                      onClick={() => void turnOff()}
                      disabled={busy || !password}
                    >
                      Turn off
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn-secondary btn-compact"
                    onClick={() => void start()}
                    disabled={busy}
                  >
                    Add an authenticator app
                  </button>
                )}
              </div>
            </div>
          </>
        )}

        {/* The setup form, the codes and the role that just started each carry
            their own way out. */}
        {!offer && !codes && !granted && (
          <button type="button" className="modal-dismiss" onClick={onClose}>
            Close
          </button>
        )}
      </div>
    </div>
  );
}
