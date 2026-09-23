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
English. `LOADERS` is therefore the whole list of languages this app can be
read in - `LOCALES` is derived from it rather than declared beside it, so the
two cannot drift.

`ui` is a live binding rather than a constant: `useLocale` sets it before the
first paint and again whenever the reader changes languages, and every
component that read `ui.something.key` at render time sees the new words on
the next render. */
import { EN } from "./en.ts";

/** What every locale must provide, member for member.

Taken from the English module rather than declared by hand, so the two cannot
drift: adding an entry to `en.ts` is what makes every other locale
incomplete, and that is exactly the pressure the completeness rule is for
(R-I18N-04). The *keys* are what a locale must match - `en.ts` is deliberately
not `as const`, or a translation would be unassignable to the English words
it replaces. Every other locale module declares itself `: Catalogue`, which
is where an omitted key fails the build. */
export type Catalogue = typeof EN;

/** Every language the interface has been finished in, and how to fetch it.

One chunk per language, fetched only by somebody who reads it (#982). They
were all in the entry chunk once, and six of the seven were 35% of the
bundle for every visitor - each reader paid for six languages they would
never see. English stays in the entry chunk: it is the type every other
locale is written against, and what a reader gets if their language cannot
be fetched at all. */
const LOADERS = {
  de: () => import("./de.ts").then((module) => module.DE),
  en: () => Promise.resolve(EN),
  es: () => import("./es.ts").then((module) => module.ES),
  fr: () => import("./fr.ts").then((module) => module.FR),
  it: () => import("./it.ts").then((module) => module.IT),
  nl: () => import("./nl.ts").then((module) => module.NL),
  pt: () => import("./pt.ts").then((module) => module.PT),
} satisfies Record<string, () => Promise<Catalogue>>;

export type Locale = keyof typeof LOADERS;

export const LOCALES = Object.keys(LOADERS) as Locale[];

/** The same list, named for callers that mean "every catalogue there is"
    rather than "every locale a player may pick" - today they are the same,
    and R-I18N-07 is the rule that keeps them so. */
export const CATALOGUE_LOCALES = LOCALES;

export const FALLBACK_LOCALE: Locale = "en";

const loaded: Partial<Record<Locale, Catalogue>> = { en: EN };
const inFlight: Partial<Record<Locale, Promise<Locale>>> = {};

function asLocale(locale: string): Locale {
  return (locale in LOADERS ? locale : FALLBACK_LOCALE) as Locale;
}

/** The catalogue the interface reads. Reassigned by `setCatalogue`. */
export let ui: Catalogue = EN;
let current: Locale = FALLBACK_LOCALE;

/** The locale `ui` is in - for the few words the platform already knows in
every language, such as a language's own name (`Intl.DisplayNames`). */
export function interfaceLocale(): Locale {
  return current;
}

/** Whether `locale`'s words are already here, so switching to it is instant. */
export function isCatalogueLoaded(locale: string): boolean {
  return loaded[asLocale(locale)] !== undefined;
}

/** Fetch `locale`'s words, once, and say which locale can now be read.

Settles with the fallback rather than rejecting when the chunk cannot be
fetched - offline, or a shell older than the deploy that renamed its chunks:
English is a worse page than the reader's language but a far better one than
none, and the update notice is what tells a stale shell to reload. */
export function loadCatalogue(locale: string): Promise<Locale> {
  const wanted = asLocale(locale);
  if (loaded[wanted]) return Promise.resolve(wanted);
  inFlight[wanted] ??= LOADERS[wanted]().then(
    (catalogue) => {
      loaded[wanted] = catalogue;
      return wanted;
    },
    () => {
      delete inFlight[wanted];
      return FALLBACK_LOCALE;
    },
  );
  return inFlight[wanted];
}

/** Read the interface in `locale` from here on.

Returns the locale actually in force. That is the fallback for anything not
in `LOADERS` - a stored choice from a build that offered more languages than
this one does, say - and the current locale for one whose words have not been
fetched yet: `loadCatalogue` first, then this. */
export function setCatalogue(locale: string): Locale {
  const chosen = asLocale(locale);
  const catalogue = loaded[chosen];
  if (!catalogue) return current;
  ui = catalogue;
  current = chosen;
  return chosen;
}

/** The catalogue for one locale, without changing what the app is reading -
or English, for one whose words have not been fetched. */
export function catalogueFor(locale: string): Catalogue {
  return loaded[asLocale(locale)] ?? EN;
}
