/** Which language the interface is read in, and where that answer comes from.

Four sources, in one order, first match wins - no merging, because a merge of
two languages is not a language:

1. **The account's setting**, so a choice follows a player to their phone.
2. **This browser's stored choice**, which is all a guest has.
3. **`navigator.languages`**, which is what a first visit has to go on.
4. **English**, which is what everybody has.

Distinct from the room's **prompt language** on purpose. That decides what a
room draws from and how a guess is folded; this decides what the buttons say.
A Dutch speaker playing an English room is ordinary, and a single preference
could not describe them (R-I18N-06). The two registries are also bound by
different things - a prompt language needs matching semantics to exist at all
(N-09), an interface locale needs only somebody to have written the words - so
they are free to diverge even though they hold the same seven today.

Resolved before the first paint. A page that renders in English and then
switches has already shown the wrong language to the person who reads slowest.
*/
import { catalogueFor, FALLBACK_LOCALE, LOCALES, type Locale } from "../content/ui/index.ts";

export { FALLBACK_LOCALE, LOCALES };
export type { Locale };

const STORAGE_KEY = "sketchy_locale";

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/** The first of the browser's languages this app is written in.

A regional tag reads down to its base, so `de-AT` gets German rather than
English: somebody who asked for Austrian German would rather have German than
a language they did not ask for at all. */
export function preferredLocale(languages: readonly string[]): Locale {
  for (const tag of languages) {
    const lower = tag.toLowerCase();
    if (isLocale(lower)) return lower;
    const base = lower.split("-")[0];
    if (isLocale(base)) return base;
  }
  return FALLBACK_LOCALE;
}

/** This browser's remembered choice, if it has one and can still read it. */
export function storedLocale(): Locale | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return isLocale(raw) ? raw : null;
  } catch {
    // A private window, or storage switched off. The browser still knows
    // what languages it reads.
    return null;
  }
}

export function rememberLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Nothing to do: the choice lasts for this tab, and an account keeps it
    // properly.
  }
}

/** The locale to read in, given everything known about this reader. */
export function resolveLocale(sources: {
  account?: string | null;
  stored?: string | null;
  browser?: readonly string[];
}): Locale {
  if (isLocale(sources.account)) return sources.account;
  if (isLocale(sources.stored)) return sources.stored;
  return preferredLocale(sources.browser ?? []);
}

/** Tell the document what language it is in.

Not cosmetic: `lang` is what a screen reader picks a voice from, what a
browser offers to translate, and what `:lang()` styling and hyphenation read.

The description tags move with it. `index.html` carries the English ones for
a crawler, which arrives before any script runs and is the reader those tags
are really for; a person who has chosen another language gets theirs here. */
export function applyDocumentLocale(locale: Locale): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  const description = catalogueFor(locale).document.description;
  for (const selector of ['meta[name="description"]', 'meta[property="og:description"]']) {
    document.querySelector(selector)?.setAttribute("content", description);
  }
}
