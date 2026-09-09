import type { ReportReason } from "../../lib/moderation.ts";

/** The rules, as data rather than as markup.

Typed rather than Markdown so a translation cannot quietly go missing: a locale
that omits a section, or invents one, fails the build rather than rendering a
page with a hole where a rule used to be. It also means no Markdown parser and
no HTML from a content file, which for text that anyone may eventually
contribute is worth more than the formatting it gives up.

The app has no i18n framework yet and this does not invent one. What it does is
put the rules in the shape the eventual one will want - a module per locale,
reviewed like code - so adding a language is a content pull request and nothing
else. */

/** The three things the rules are about. Ids are English and never translated:
they are anchors, and a link to `#conduct` has to survive being read in
Italian. */
export type RuleSectionId = "conduct" | "content" | "fair-play";

export const RULE_SECTION_IDS: RuleSectionId[] = ["conduct", "content", "fair-play"];

/** One rule, anchored by the category a moderator records against it.

This is what makes a decision checkable: a notice saying *recorded as spam*
links to `#spam`, and the player reads the rule they are said to have broken
rather than being left with a moderator's sentence and a guess (R-RULES-02). */
export interface Rule {
  id: ReportReason;
  heading: string;
  /** Paragraphs. Plain strings: the page renders text, never markup. */
  body: string[];
  /** Concrete cases, where saying "for example" is clearer than another
      paragraph of principle. Empty when the rule needs none. */
  examples: string[];
}

export interface RuleSection {
  id: RuleSectionId;
  heading: string;
  blurb: string;
  rules: Rule[];
}

export interface RulesDocument {
  /** The locale this document is written in, as the app names languages. */
  locale: string;
  title: string;
  /** What the introduction is called, so it reads as a section like the
      others rather than as loose text above them. */
  introHeading: string;
  /** Read before the rules themselves: what they are for and how they are
      applied, which is the part that stops a list of prohibitions reading as
      a threat. */
  intro: string[];
  sections: RuleSection[];
  /** What happens when a rule is broken, in the same general terms the
      warning notice uses (R-MOD-19). */
  enforcement: { heading: string; body: string[] };
}
