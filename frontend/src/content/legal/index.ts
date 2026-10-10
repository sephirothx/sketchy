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

/** When the documents last changed, shown under each title with a link to
their history. `reference` is a SHA-256 of the English text, the reference:
`tests/legal.test.mjs` fails when that text changes and this does not, so the
date cannot go stale by being forgotten. A change to a translation alone
leaves both as they are - it says the same thing better. */
export const LEGAL_REVISION = {
  date: "2026-10-10",
  reference: "bd7e7ea2d510ec9ad5a085b32e0e651662c3d2fbe65dbf43fcfba06b8d811493",
} as const;

/** The public history of the documents in *locale*, every change with its
date, as osu! links its own. */
export function legalHistoryUrl(locale: string | null | undefined): string {
  return `https://github.com/sephirothx/sketchy/commits/main/frontend/src/content/legal/${legalLocaleFor(locale)}.ts`;
}

/** The locale the documents are shown in for *locale*: an exact match, then
the base of a regional tag, then English. */
export function legalLocaleFor(locale: string | null | undefined): string {
  if (!locale) return LEGAL_FALLBACK_LOCALE;
  const wanted = locale.toLowerCase();
  if (DOCUMENTS[wanted]) return wanted;
  const base = wanted.split("-")[0];
  return DOCUMENTS[base] ? base : LEGAL_FALLBACK_LOCALE;
}

/** The documents in the best language available for *locale*. */
export function legalFor(locale: string | null | undefined): LegalDocuments {
  return DOCUMENTS[legalLocaleFor(locale)];
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
