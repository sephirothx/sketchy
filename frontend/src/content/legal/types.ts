/** The privacy notice and the terms, as data rather than as markup (#1417).

The same shape as the rules, for the same reasons: typed, so a locale that
omits a section fails the build instead of publishing a notice with a hole in
it; plain strings, so a content file never carries HTML. Two documents per
locale, read on one page with a switch between them. */

/** Section ids are English and never translated: they are anchors, and a
link to `/privacy#rights` has to land in every language. */
export type PrivacySectionId =
  | "operator"
  | "data"
  | "purposes"
  | "visibility"
  | "recipients"
  | "retention"
  | "rights"
  | "cookies"
  | "age"
  | "changes";

export type TermsSectionId =
  | "agreement"
  | "age"
  | "accounts"
  | "fair-play"
  | "content"
  | "moderation"
  | "availability"
  | "liability"
  | "leaving"
  | "law"
  | "changes";

export interface LegalSection<Id extends string> {
  id: Id;
  heading: string;
  /** Paragraphs. `{contact}` is replaced with the operator's address, and
      `{age}` with the minimum age; nothing else is interpreted. */
  body: string[];
  /** A list after the paragraphs, where one reads better than prose. */
  items?: string[];
}

export interface LegalDocument<Id extends string> {
  title: string;
  /** Read before the sections: what the document is and who it binds. */
  intro: string[];
  sections: LegalSection<Id>[];
}

export interface LegalDocuments {
  /** The locale these documents are written in, as the app names languages. */
  locale: string;
  privacy: LegalDocument<PrivacySectionId>;
  terms: LegalDocument<TermsSectionId>;
}
