/** The two things a catalogue entry needs that a template literal cannot do.

**Plurals.** English has two forms and most code here used to pick between
them with `count === 1 ? "" : "s"`, which is English grammar written as if it
were logic: it is wrong in five of the seven languages the moment a count
reaches zero, and wrong in Polish at 22. `Intl.PluralRules` answers with the
category the *reader's* language actually has, so a locale writes the forms it
needs - `one`/`other` for English, `one`/`few`/`many`/`other` elsewhere - and
no entry has to know which those are.

**Numbers.** A thousand is `1,000` here and `1.000` in German. `Intl` knows;
`toLocaleString()` with no locale reads the device's, which is not necessarily
the one the interface is being read in.

Both are bound to a locale once, in the catalogue module for that language, so
an entry never repeats it. */

/** The plural categories a language can use. */
export type PluralForms = { other: string } & Partial<
  Record<Intl.LDMLPluralRule, string>
>;

export type Formatters = {
  /** `1st`, `2nd`, `3rd` - in whatever shape this locale gives them. */
  ordinal: (value: number) => string;
  /** The form of a word that goes with `count`, in this locale's own rules. */
  plural: (count: number, forms: PluralForms) => string;
  /** `count` written the way this locale writes numbers. */
  number: (value: number) => string;
  /** `count` and its word together, which is what nearly every caller wants. */
  counted: (count: number, forms: PluralForms) => string;
};

/** The formatters for one locale, built once per catalogue module.

`ordinalSuffixes` is per language and is the locale's own business: English
needs four (`st`, `nd`, `rd`, `th`) keyed by the ordinal plural category,
German writes `1.` for all of them, and a language with none omits it and
gets the bare number. */
export function formattersFor(
  locale: string,
  ordinalSuffixes: Partial<Record<Intl.LDMLPluralRule, string>> = {},
): Formatters {
  const rules = new Intl.PluralRules(locale);
  const ordinals = new Intl.PluralRules(locale, { type: "ordinal" });
  const numbers = new Intl.NumberFormat(locale);
  const plural = (count: number, forms: PluralForms): string =>
    forms[rules.select(count)] ?? forms.other;
  return {
    plural,
    number: (value) => numbers.format(value),
    ordinal: (value) =>
      `${numbers.format(value)}${ordinalSuffixes[ordinals.select(value)] ?? ""}`,
    counted: (count, forms) => `${numbers.format(count)} ${plural(count, forms)}`,
  };
}
