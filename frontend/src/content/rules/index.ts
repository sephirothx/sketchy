import { RULES_EN } from "./en.ts";
import type { RulesDocument } from "./types.ts";

export type { Rule, RuleSection, RulesDocument } from "./types.ts";
export { RULE_SECTION_IDS } from "./types.ts";

/** Every locale the rules have been written in.

English is the reference: it is what the others are translations of, and what
anybody reads whose language is not here yet. Adding a language is one module
and one line - a content pull request, reviewed like the rest of the
repository, which is also how the wiki this is modelled on does it.

There is no framework behind this on purpose. The app translates nothing else
yet, and inventing a translation system for one page would leave the rules
using a mechanism nothing else uses. What this does is keep them in the shape
the eventual one will want. */
const DOCUMENTS: Record<string, RulesDocument> = {
  en: RULES_EN,
};

export const RULES_FALLBACK_LOCALE = "en";

/** The rules in the best language available for *locale*.

Falls back to English rather than to nothing: a player whose language has not
been written yet must still be able to read what they are held to. An exact
match wins; then the base of a regional tag, so `it-CH` reads Italian once
Italian exists. */
export function rulesFor(locale: string | null | undefined): RulesDocument {
  if (!locale) return DOCUMENTS[RULES_FALLBACK_LOCALE];
  const wanted = locale.toLowerCase();
  return (
    DOCUMENTS[wanted] ??
    DOCUMENTS[wanted.split("-")[0]] ??
    DOCUMENTS[RULES_FALLBACK_LOCALE]
  );
}

/** The locales the rules exist in, for a caller that wants to offer them. */
export function rulesLocales(): string[] {
  return Object.keys(DOCUMENTS);
}

/** Where a decision's category is explained.

The link a notice uses when it says what a decision was recorded as. Every
category is a rule's anchor by construction - the rule carries the category as
its id - so this cannot point at a section that is not there. */
export function ruleAnchorFor(category: string): string {
  return `/rules#${category}`;
}
