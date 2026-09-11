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
import { EN } from "./en.ts";

/** What every locale must provide, member for member. */
export type Catalogue = typeof EN;

/** Every language the interface has been finished in. */
const CATALOGUES = {
  en: EN,
} satisfies Record<string, Catalogue>;

export type Locale = keyof typeof CATALOGUES;

export const LOCALES = Object.keys(CATALOGUES) as Locale[];

export const FALLBACK_LOCALE: Locale = "en";

/** The catalogue the interface reads. Reassigned by `setCatalogue`. */
export let ui: Catalogue = CATALOGUES[FALLBACK_LOCALE];

/** Read the interface in `locale` from here on.

Returns the locale actually in force, which is the fallback for anything not
in `CATALOGUES` - a stored choice from a build that offered more languages
than this one does, say. */
export function setCatalogue(locale: string): Locale {
  const chosen = (locale in CATALOGUES ? locale : FALLBACK_LOCALE) as Locale;
  ui = CATALOGUES[chosen];
  return chosen;
}

/** The catalogue for one locale, without changing what the app is reading. */
export function catalogueFor(locale: string): Catalogue {
  return CATALOGUES[(locale in CATALOGUES ? locale : FALLBACK_LOCALE) as Locale];
}
