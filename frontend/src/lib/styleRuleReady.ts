/** Whether the page has parsed a rule whose selector names `selector`: in any
    stylesheet it can read, inside layers, media blocks and imports too. A
    sheet from another origin (the web fonts) cannot be read and is skipped. */
export function hasStyleRule(selector: string): boolean {
  const walk = (rules: CSSRuleList): boolean => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule && rule.selectorText.includes(selector)) return true;
      if (rule instanceof CSSImportRule && rule.styleSheet && walk(rule.styleSheet.cssRules)) return true;
      if ("cssRules" in rule && rule.cssRules instanceof CSSRuleList && walk(rule.cssRules)) return true;
    }
    return false;
  };
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    if (walk(rules)) return true;
  }
  return false;
}

/**
 * Resolves true once the page has a rule for `selector`, or false if it has
 * none after `timeoutMs`.
 *
 * Vite's preload helper waits for a stylesheet it inserts for a lazy chunk,
 * but not for one another chunk's prefetch already put in the page: it sees
 * the link and skips it, loaded or not. The languages question shares its
 * sheet with Settings, which the lobby prefetches, so the question asks for
 * its own rule rather than for links to settle (review of #1312) - and a
 * timeout is an answer of "not there", never a guess that it arrived: a
 * question drawn without its rules is the bug this guards against (review of
 * #1312, round two).
 */
export function whenStyleRule(selector: string, timeoutMs = 3000): Promise<boolean> {
  if (hasStyleRule(selector)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const links = [...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')];
    let settled = false;
    const finish = (ready: boolean) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      window.clearInterval(poll);
      for (const link of links) {
        link.removeEventListener("load", check);
        link.removeEventListener("error", check);
      }
      resolve(ready);
    };
    const check = () => {
      if (hasStyleRule(selector)) finish(true);
    };
    // A link's load answers at once; the poll covers a sheet that arrives as a
    // style element, which fires nothing.
    for (const link of links) {
      link.addEventListener("load", check);
      link.addEventListener("error", check);
    }
    const poll = window.setInterval(check, 100);
    const timer = window.setTimeout(() => finish(hasStyleRule(selector)), timeoutMs);
  });
}
