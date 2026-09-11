/** The interface's words, in the reader's language.

One module per locale, declared against the English one, so a locale that
omits a key or invents one fails the build rather than rendering a screen with
a hole in it (R-I18N-04). It is the shape `content/rules/` already chose for
the rules, generalised: adding a language is a content pull request and
nothing else.

There is no framework behind this on purpose. A catalogue of plain functions
type-checks its own parameters, ships no runtime parser, and cannot be handed
a key that does not exist.

**A locale appears here only when it is complete.** Offering a language and
finishing it are the same act: a page that falls back to English halfway
through is worse than one honestly written in another language, and a reader
cannot tell a missing translation from a sentence somebody chose to leave in
English. `CATALOGUES` is therefore the whole list of languages this app can be
read in - `LOCALES` is derived from it rather than declared beside it, so the
two cannot drift.

`ui` is a live binding rather than a constant: `useLocale` sets it before the
first paint and again whenever the reader changes languages, and every
component that read `ui.something.key` at render time sees the new words on
the next render. */
import { DE } from "./de.ts";
import { EN } from "./en.ts";
import { ES } from "./es.ts";
import { FR } from "./fr.ts";
import { IT } from "./it.ts";
import { NL } from "./nl.ts";
import { PT } from "./pt.ts";

/** What every locale must provide, member for member.

Taken from the English module rather than declared by hand, so the two cannot
drift: adding an entry to `en.ts` is what makes every other locale
incomplete, and that is exactly the pressure the completeness rule is for
(R-I18N-04). The *keys* are what a locale must match - `en.ts` is deliberately
not `as const`, or a translation would be unassignable to the English words
it replaces. */
export type Catalogue = typeof EN;

/** Every language the interface has been finished in. */
const CATALOGUES = {
  de: DE,
  en: EN,
  es: ES,
  fr: FR,
  it: IT,
  nl: NL,
  pt: PT,
} satisfies Record<string, Catalogue>;

export type Locale = keyof typeof CATALOGUES;

export const LOCALES = Object.keys(CATALOGUES) as Locale[];

/** The same list, named for callers that mean "every catalogue there is"
    rather than "every locale a player may pick" - today they are the same,
    and R-I18N-07 is the rule that keeps them so. */
export const CATALOGUE_LOCALES = LOCALES;

export const FALLBACK_LOCALE: Locale = "en";

/** The catalogue the interface reads. Reassigned by `setCatalogue`. */
export let ui: Catalogue = CATALOGUES[FALLBACK_LOCALE];
let current: Locale = FALLBACK_LOCALE;

/** The locale `ui` is in - for the few words the platform already knows in
every language, such as a language's own name (`Intl.DisplayNames`). */
export function interfaceLocale(): Locale {
  return current;
}

/** Read the interface in `locale` from here on.

Returns the locale actually in force, which is the fallback for anything not
in `CATALOGUES` - a stored choice from a build that offered more languages
than this one does, say. */
export function setCatalogue(locale: string): Locale {
  const chosen = (locale in CATALOGUES ? locale : FALLBACK_LOCALE) as Locale;
  ui = CATALOGUES[chosen];
  current = chosen;
  return chosen;
}

/** The catalogue for one locale, without changing what the app is reading. */
export function catalogueFor(locale: string): Catalogue {
  return CATALOGUES[(locale in CATALOGUES ? locale : FALLBACK_LOCALE) as Locale];
}
