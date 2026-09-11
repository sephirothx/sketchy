import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Squiggle, Wordmark } from "../components/icons";
import { SectionLabel } from "../components/ui/Card";
import {
  completePasswordReset,
  confirmEmailToken,
  passwordResetLinkIsUsable,
  requestPasswordReset,
} from "../lib/accountRecovery";
import { useAuthStore } from "../store/authStore";
import { MIN_PASSWORD_LENGTH, PASSWORD_TOO_SHORT } from "../lib/passwordPolicy";
import { refusalText } from "../lib/refusals.ts";
import { ui } from "../content/ui/index.ts";

type Mode = "forgot" | "reset" | "verify";

/** The three steps that happen outside a signed-in session.

One page rather than three: they are the same card with different copy, they
are all reached from a link in a message rather than from the app, and they all
end by sending the player back to the lobby. */
export function AccountRecoveryPage({ mode }: { mode: Mode }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const fetchMe = useAuthStore((state) => state.fetchMe);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  // Verification starts in flight: the effect below runs on arrival, and
  // setting this from inside it would be a state write during an effect.
  const [busy, setBusy] = useState(mode === "verify" && token !== "");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // null while the answer is still coming. A reset link is checked when the
  // page opens rather than when the form is sent, so nobody chooses a password
  // only to be told the link was already spent.
  // A link with no token at all is answered here rather than in the effect,
  // where a synchronous state write would be a cascading render.
  const [linkUsable, setLinkUsable] = useState<boolean | null>(
    mode === "reset" ? (token ? null : false) : true,
  );

  useEffect(() => {
    if (mode !== "verify" || !token) return;
    let cancelled = false;
    void confirmEmailToken(token)
      .then(({ address }) => {
        if (cancelled) return;
        setDone(`${address} is confirmed. You can now recover this account.`);
        // The account gained an address; anything showing its state should say so.
        void fetchMe();
      })
      .catch((confirmError) => {
        if (cancelled) return;
        setError(
          refusalText(confirmError, ui.accountRecoveryPage.thatConfirmationLinkCouldNotBe),
        );
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, token, fetchMe]);

  useEffect(() => {
    if (mode !== "reset" || !token) return;
    let cancelled = false;
    void passwordResetLinkIsUsable(token)
      .then(({ valid }) => {
        if (!cancelled) setLinkUsable(valid);
      })
      // A check that could not be made is not a link that is broken; let the
      // form be tried, where the answer is authoritative anyway.
      .catch(() => {
        if (!cancelled) setLinkUsable(true);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, token]);

  async function submitForgot(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { detail } = await requestPasswordReset(identifier.trim());
      setDone(detail);
    } catch (requestError) {
      setError(
        refusalText(requestError, ui.accountRecoveryPage.somethingWentWrongPleaseTryAgain),
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitReset(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(PASSWORD_TOO_SHORT);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await completePasswordReset(token, password);
      await fetchMe();
      setDone("Your password is set and you are signed in again.");
    } catch (resetError) {
      setError(
        refusalText(resetError, ui.accountRecoveryPage.somethingWentWrongPleaseTryAgain),
      );
    } finally {
      setBusy(false);
    }
  }

  const heading =
    mode === "forgot"
      ? "Reset your password"
      : mode === "reset"
        ? // Nothing is being chosen when the link is dead, and a heading that
          // says otherwise is the page arguing with its own message.
          linkUsable === false
          ? "That link no longer works"
          : "Choose a new password"
        : "Confirming your email";

  return (
    <main className="recovery-page">
      <div className="recovery-card">
        <section className="recovery-aside" aria-hidden="true">
          <h2>{ui.accountRecoveryPage.evenBestGuessersForgetSometimes}</h2>
          <Squiggle width={110} color="var(--primary)" />
          <p>
            {ui.accountRecoveryPage.weRsquoLlSendSecureTime}
          </p>
        </section>
        <section className="recovery-form">
        <Wordmark size={22} />
        <div className="recovery-heading">
          <SectionLabel>{ui.accountRecoveryPage.accountHelp}</SectionLabel>
          <h1>{heading}</h1>
        </div>

        {done ? (
          <>
            <p className="recovery-body">{done}</p>
            <Link className="modal-button" to="/">
              {ui.accountRecoveryPage.backLobby}
            </Link>
          </>
        ) : mode === "forgot" ? (
          <form onSubmit={submitForgot} className="auth-form">
            <p className="recovery-body">
              {ui.accountRecoveryPage.enterYourUsernameYourConfirmedEmail}
            </p>
            <label htmlFor="recovery-identifier">{ui.accountRecoveryPage.usernameEmail}</label>
            <input
              id="recovery-identifier"
              value={identifier}
              onChange={(event) => {
                setIdentifier(event.target.value);
                setError(null);
              }}
              autoComplete="username"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              required
            />
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="modal-button" disabled={busy}>
              {busy ? "Please wait…" : "Send a reset link"}
            </button>
          </form>
        ) : mode === "reset" && linkUsable === false ? (
          <>
            <p className="recovery-body">
              {ui.accountRecoveryPage.thatResetLinkHasExpiredHas}
            </p>
            <Link className="modal-button" to="/forgot-password">
              {ui.accountRecoveryPage.sendNewOne}
            </Link>
          </>
        ) : mode === "reset" && linkUsable === null ? (
          <p className="recovery-body">{ui.accountRecoveryPage.checkingThatLink}</p>
        ) : mode === "reset" ? (
          <form onSubmit={submitReset} className="auth-form">
            <p className="recovery-body">
              {ui.accountRecoveryPage.everySignedDeviceWillBeSigned}
            </p>
            <label htmlFor="recovery-password">{ui.accountRecoveryPage.newPassword}</label>
            <input
              id="recovery-password"
              type="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              required
            />
            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="modal-button" disabled={busy || !token}>
              {busy ? "Please wait…" : "Set password"}
            </button>
          </form>
        ) : (
          <>
            <p className="recovery-body">
              {error ?? (busy ? "One moment…" : "Nothing to confirm.")}
            </p>
            <Link className="modal-button" to="/">
              {ui.accountRecoveryPage.backLobby}
            </Link>
          </>
        )}

        {!done && mode !== "verify" && error === null && (
          <p className="auth-switch">
            <Link className="auth-link" to="/">
              {ui.accountRecoveryPage.backLobby}
            </Link>
          </p>
        )}
        </section>
      </div>
    </main>
  );
}
