/** What the first paint waits for, and for how long.

The interface locale resolves account first (R-I18N-06), and the account is
only known once `/api/auth/me` has answered - so a page drawn before that
answer is drawn in the browser's language, and a German account on a fresh
browser watches the lobby switch languages under it. The first paint therefore
waits for the account. Bounded, because a server that is slow or gone must
cost a moment and not the page: past the bound the browser's order stands, and
the account's choice arrives as an ordinary update, exactly as before. */
export const FIRST_PAINT_WAIT_MS = 2000;

/** Settles when `work` does, or after `waitMs` - whichever is first - and never
rejects: the page is drawn either way. */
export function beforeFirstPaint(
  work: Promise<unknown>,
  waitMs: number = FIRST_PAINT_WAIT_MS,
): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, waitMs);
    const done = () => {
      clearTimeout(timer);
      resolve();
    };
    work.then(done, done);
  });
}
