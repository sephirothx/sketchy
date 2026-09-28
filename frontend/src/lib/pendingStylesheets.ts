/**
 * Resolves once every stylesheet link already in the page has loaded (or
 * failed), or after `timeoutMs`, whichever is first.
 *
 * Vite's preload helper waits for a stylesheet it inserts for a lazy chunk,
 * but not for one another chunk's prefetch already put in the page: it sees
 * the link, and skips it, loaded or not. The languages question shares its
 * sheet with Settings, which the lobby prefetches, so in that window it could
 * render before its rules (review of #1312). Bounded, so a link that failed
 * before anybody listened costs a moment rather than the question.
 */
export function pendingStylesheets(timeoutMs = 3000): Promise<void> {
  const pending = [...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')]
    .filter((link) => link.sheet === null);
  if (pending.length === 0) return Promise.resolve();
  return new Promise((resolve) => {
    let left = pending.length;
    const timer = window.setTimeout(resolve, timeoutMs);
    const settle = () => {
      left -= 1;
      if (left > 0) return;
      window.clearTimeout(timer);
      resolve();
    };
    for (const link of pending) {
      link.addEventListener("load", settle, { once: true });
      link.addEventListener("error", settle, { once: true });
    }
  });
}
