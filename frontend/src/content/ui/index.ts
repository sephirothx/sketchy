/** The interface's words, in the reader's language.

One module per locale, declared against the English one, so a locale that
omits a key or invents one fails the build rather than rendering a screen with
a hole in it (R-I18N-04). It is the shape `content/rules/` already chose for
the rules, generalised: adding a language is a content pull request and
nothing else.

There is no framework behind this on purpose. A catalogue of plain functions
type-checks its own parameters, ships no runtime parser, and cannot be handed
a key that does not exist.

`ui` is English until #763 gives the app a locale to resolve; the components
already read through it, so that change reaches every screen at once. */
import { EN } from "./en.ts";

/** What every locale must provide, member for member. */
export type Catalogue = typeof EN;

export const FALLBACK_LOCALE = "en";

/** The catalogue the interface reads. */
export const ui: Catalogue = EN;
