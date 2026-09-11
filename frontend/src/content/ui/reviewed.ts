/** Which translated entries a native reader has actually signed off.

Completeness and quality are two different promises, and only one of them can
be a build rule. The compiler already guarantees that every locale defines
every key (R-I18N-04) - that is what stops a German page falling back to
English halfway down. It cannot tell whether the German is any *good*, and
pretending otherwise by shipping the six locales unmarked would quietly turn a
machine draft into a finished translation.

So the draft ships, complete, and this file is the debt: every key a native
reader has confirmed, per locale. The six are at zero, and
`tests/localeReview.test.mjs` prints the count so it is visible in CI rather
than remembered. **A locale reaching 100% is a launch gate, not a build gate**
(R-I18N-07) - the same shape `#691` used for the prompt lists, and for the
same reason: a drafted translation is honest about being one.

Keys are `"<group>.<entry>"`, as the catalogue nests them. A key nobody
reviewed is simply absent; there is no `false` to maintain.
*/
import type { Locale } from "./index.ts";

export const REVIEWED: Record<Locale, ReadonlySet<string>> = {
  // English is the reference: it is written here rather than translated, so
  // there is nothing for a native reader to check it against.
  en: new Set(),
  de: new Set(),
  es: new Set(),
  fr: new Set(),
  it: new Set(),
  nl: new Set(),
  pt: new Set(),
};
