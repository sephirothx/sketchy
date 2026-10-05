import { LEGAL_DE } from "./de.ts";
import { LEGAL_EN } from "./en.ts";
import { LEGAL_ES } from "./es.ts";
import { LEGAL_FR } from "./fr.ts";
import { LEGAL_IT } from "./it.ts";
import { LEGAL_NL } from "./nl.ts";
import { LEGAL_PL } from "./pl.ts";
import { LEGAL_PT } from "./pt.ts";
import type { LegalDocuments } from "./types.ts";
import { MINIMUM_AGE } from "../../lib/minimumAge.ts";

export type {
  LegalDocument,
  LegalDocuments,
  LegalSection,
  PrivacySectionId,
  TermsSectionId,
} from "./types.ts";

export { MINIMUM_AGE } from "../../lib/minimumAge.ts";

/** The privacy notice and the terms in every interface language (#1417).

English is the reference, as for the rules, and the other seven are
translations of it: machine-drafted like the rest of the interface and
awaiting a native reader (#784). Kept out of `content/ui/` for the reason the
rules are - a legal text wants a different review bar from a button label. */
const DOCUMENTS: Record<string, LegalDocuments> = {
  de: LEGAL_DE,
  en: LEGAL_EN,
  es: LEGAL_ES,
  fr: LEGAL_FR,
  it: LEGAL_IT,
  nl: LEGAL_NL,
  pl: LEGAL_PL,
  pt: LEGAL_PT,
};

export const LEGAL_FALLBACK_LOCALE = "en";

/** The documents in the best language available for *locale*: an exact
match, then the base of a regional tag, then English. */
export function legalFor(locale: string | null | undefined): LegalDocuments {
  if (!locale) return DOCUMENTS[LEGAL_FALLBACK_LOCALE];
  const wanted = locale.toLowerCase();
  return (
    DOCUMENTS[wanted] ?? DOCUMENTS[wanted.split("-")[0]] ?? DOCUMENTS[LEGAL_FALLBACK_LOCALE]
  );
}

/** The locales the documents exist in. */
export function legalLocales(): string[] {
  return Object.keys(DOCUMENTS);
}

/** A paragraph with its two placeholders filled: the operator's address, or
*fallback* where this deployment has none, and the minimum age. */
export function legalText(text: string, contact: string): string {
  return text.replaceAll("{contact}", contact).replaceAll("{age}", String(MINIMUM_AGE));
}
