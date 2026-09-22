/** Where a decision's category is explained.

The link a notice uses when it says what a decision was recorded as. Every
category is a rule's anchor by construction - the rule carries the category as
its id - so this cannot point at a section that is not there.

A module of its own because the notices that link here are mounted on every
page, and the rules themselves - seven documents - are read only on the rules
page: importing the link from `index.ts` carried all seven into the entry
chunk for every visitor (#982). */
export function ruleAnchorFor(category: string): string {
  return `/rules#${category}`;
}
