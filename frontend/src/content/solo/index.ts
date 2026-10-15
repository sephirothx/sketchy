import { SOLO_DE } from "./de.ts";
import { SOLO_EN, type SoloCopy } from "./en.ts";
import { SOLO_ES } from "./es.ts";
import { SOLO_FR } from "./fr.ts";
import { SOLO_IT } from "./it.ts";
import { SOLO_NL } from "./nl.ts";
import { SOLO_PL } from "./pl.ts";
import { SOLO_PT } from "./pt.ts";

export type { SoloCopy } from "./en.ts";

/** Solo's page copy in every interface language (#1434). Imported by the
    page alone, so all eight travel in its chunk and none in the first load. */
const COPY: Record<string, SoloCopy> = {
  de: SOLO_DE,
  en: SOLO_EN,
  es: SOLO_ES,
  fr: SOLO_FR,
  it: SOLO_IT,
  nl: SOLO_NL,
  pl: SOLO_PL,
  pt: SOLO_PT,
};

/** The page's copy in the interface's language, English for one not written. */
export function soloCopyFor(locale: string): SoloCopy {
  return COPY[locale] ?? COPY[locale.split("-")[0]] ?? SOLO_EN;
}

/** Every locale the copy is written in: the interface's eight. */
export function soloCopyLocales(): string[] {
  return Object.keys(COPY);
}
