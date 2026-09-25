import { useId, useState, type CSSProperties } from "react";
import { needsIdentity, useAuthStore } from "../store/authStore";
import { AuthDialog } from "./AccountMenu";
import { authSubmitter, type AuthMode } from "../lib/authSubmit";
import { MAX_NICKNAME_LENGTH, nicknameError } from "../lib/roomEntryState";
import { refusalText } from "../lib/refusals.ts";
import { firstRunLine } from "../lib/firstRunLines";
import { DOODLE_SPRITE } from "../lib/avatarDoodles";
import { firstRunArt, type FirstRunDoodle } from "../lib/firstRunArt";
import { ui } from "../content/ui/index.ts";

/**
 * Shown only until the visitor has an account or a name of their own.
 *
 * A name tag, because the one decision on the page should look like a party
 * rather than a sign-up (#588): "Hello, my name is ___", and a button that
 * sticks it on. It is the only thing the block asks for, and - this is the
 * point of #589 - it promises nothing more than a name. What plays is Quick
 * play, beside the room list.
 *
 * Beside the tag, what the game is: a line from the pool (#590, see
 * `lib/firstRunLines.ts`) over the one sentence that always explains it. The
 * account offer is one quiet line at the end, on every width. It used to lead
 * the desktop with Create an account in the primary colour, asking a visitor
 * to commit before the page had shown them a single drawing.
 *
 * One layout for every width: the tag, then the words, in that order both in
 * the DOM and on screen. Inline rather than modal, so browsing and logging in
 * are never gated, and a returning player on a new device reaches "Log in"
 * without being asked to invent a guest name.
 */
/** One doodle, leaning the way this visit dealt it. */
function doodle({ name, rotate, shift, scale }: FirstRunDoodle) {
  return (
    <svg
      key={name}
      className="first-run-doodle"
      viewBox="0 0 24 24"
      style={{
        "--doodle-rotate": `${rotate}deg`,
        "--doodle-shift": `${shift}px`,
        "--doodle-scale": scale,
      } as CSSProperties}
    >
      <use href={`${DOODLE_SPRITE}#${name}`} />
    </svg>
  );
}

export function FirstRunIdentity() {
  const user = useAuthStore((s) => s.user);
  const hasResolved = useAuthStore((s) => s.hasResolved);
  const setDisplayName = useAuthStore((s) => s.setDisplayName);
  const login = useAuthStore((s) => s.login);
  const register = useAuthStore((s) => s.register);

  const fieldId = useId();
  const art = firstRunArt();
  const [mode, setMode] = useState<AuthMode | null>(null);
  // Shared, so that typing a name here and pressing Create or Join instead of
  // this form's own button means the same thing.
  const name = useAuthStore((s) => s.nameDraft);
  const setName = useAuthStore((s) => s.setNameDraft);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Nothing until the initial GET /api/auth/me settles. A null user means
  // "not known yet" as well as "nobody", and offering these controls in that
  // window lets a submission race the provisioning request: both are
  // cookieless, both create an account, and the later cookie discards the
  // name that was just chosen.
  if (!hasResolved) return null;

  // Once there is a name, or an account, this never appears again - unless
  // the name is a guest's that somebody online took while they were away
  // (R-ACCT-09), who is asked for another here before they can play.
  if (!needsIdentity(user)) return null;
  const takenName = user?.nameInUse ? user.displayName : null;

  async function nameMe(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const chosen = name.trim();
    const invalid = nicknameError(chosen);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      await setDisplayName(chosen);
    } catch (saveError) {
      setError(
        refusalText(saveError, ui.firstRunIdentity.couldNotSaveThatNamePlease),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface-card first-run" aria-labelledby={`${fieldId}-heading`}>
      {/* The card is the size container; its contents are the grid, because a
          card cannot answer a container query about itself. */}
      <div className="first-run-inner">
      {/* The deployment's own doodles, one side and the other, so that on a
          wide card the tag and the words sit in the middle of the block rather
          than against its left edge. Narrower, one is left, in the bottom-right
          corner. Which three, which side and how each leans is this visit's
          deal (`lib/firstRunArt.ts`), and none of it changes the card's size.
          Decorative either way: the tag and the words say everything. */}
      <div className="first-run-art is-left" aria-hidden="true">
        {art.left.map(doodle)}
      </div>
      {takenName && (
        <p className="first-run-name-in-use" role="status">
          {ui.firstRunIdentity.nameInUse({ name: takenName })}
        </p>
      )}
      <form className="first-run-tag" onSubmit={nameMe}>
        <label className="first-run-tag-top" htmlFor={`${fieldId}-name`}>
          {ui.firstRunIdentity.helloMyNameIs}
        </label>
        <div className="first-run-guest-row">
          {/* Search type suppresses Android Chrome's unrelated autofill toolbar,
              matching every other name field in the app. */}
          <input
            id={`${fieldId}-name`}
            type="search"
            inputMode="text"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setError(null);
            }}
            maxLength={MAX_NICKNAME_LENGTH}
            placeholder={ui.firstRunIdentity.displayName}
            autoComplete="nickname"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="done"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
          />
        </div>
        <button type="submit" className="btn btn-secondary first-run-guest-submit" disabled={busy}>
          {busy ? "\u2026" : ui.firstRunIdentity.stickItOn}
        </button>
        {error && (
          <p id={`${fieldId}-error`} className="auth-error" role="alert">{error}</p>
        )}
      </form>

      <div className="first-run-say">
        <h2 id={`${fieldId}-heading`} className="first-run-heading">{firstRunLine()}</h2>
        <p className="first-run-copy">{ui.firstRunIdentity.oneLineExplainer}</p>
        <p className="first-run-account">
          {ui.firstRunIdentity.beenHereBefore}{" "}
          <button type="button" className="first-run-login" onClick={() => setMode("login")}>
            {ui.firstRunIdentity.logIn}
          </button>
          {" · "}
          <button type="button" className="first-run-signup" onClick={() => setMode("claim")}>
            {ui.firstRunIdentity.createAccount}
          </button>
        </p>
      </div>


      <div className="first-run-art is-right" aria-hidden="true">
        {art.right.map(doodle)}
      </div>
      </div>
      {mode && (
        <AuthDialog
          mode={mode}
          onClose={() => setMode(null)}
          onSwitchMode={setMode}
          onSubmit={authSubmitter(mode, login, register)}
        />
      )}
    </section>
  );
}
