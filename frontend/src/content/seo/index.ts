import { SEO_DE } from "./de.ts";
import { SEO_EN } from "./en.ts";
import { SEO_ES } from "./es.ts";
import { SEO_FR } from "./fr.ts";
import { SEO_IT } from "./it.ts";
import { SEO_NL } from "./nl.ts";
import { SEO_PL } from "./pl.ts";
import { SEO_PT } from "./pt.ts";
import type { SeoCopy } from "./types.ts";
import type { Locale } from "../ui/index.ts";

export type { SeoCopy } from "./types.ts";

/** Every interface language's search descriptions (#1459). A `Record` over
`Locale`, so a language added to the interface fails the build here until its
descriptions are written. */
export const SEO_COPY: Record<Locale, SeoCopy> = {
  de: SEO_DE,
  en: SEO_EN,
  es: SEO_ES,
  fr: SEO_FR,
  it: SEO_IT,
  nl: SEO_NL,
  pl: SEO_PL,
  pt: SEO_PT,
};
