/** The minimum age to play (#1417): the EU's default age of digital consent,
so no parental-consent flow is needed. Stated once - the terms, the privacy
notice and every catalogue line that names it read this - and kept out of
`content/legal/` so the name step and the account dialog can say it without
pulling every language's legal text into the first-load bundle. */
export const MINIMUM_AGE = 16;
