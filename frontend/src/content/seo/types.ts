/** What a search result says under each public page's title (#1459).

Read by the build alone (`scripts/seo-pages.mjs`), which writes it into the
pages the server serves; nothing in the app imports it, so none of it is in
the first-load budget. The titles are not here: a page's title is what its tab
says, so it comes from `content/ui/` and the app sets the same words. Typed per
locale like the rules and the legal texts, so a language that leaves a
description out fails the build (R-I18N-04). */
export interface SeoCopy {
  /** The locale this copy is written in, as the app names languages. */
  locale: string;
  home: string;
  rules: string;
  terms: string;
  privacy: string;
  solo: string;
  /** An official word list's page. */
  promptList: (p: { name: string; count: number }) => string;
}
