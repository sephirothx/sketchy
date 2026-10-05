import assert from "node:assert/strict";
import test from "node:test";

import {
  LEGAL_FALLBACK_LOCALE,
  MINIMUM_AGE,
  legalFor,
  legalLocales,
  legalText,
} from "../src/content/legal/index.ts";
import { LOCALES } from "../src/content/ui/index.ts";

const DOCUMENTS = ["privacy", "terms"];

function placeholders(section) {
  const text = [...section.body, ...(section.items ?? [])].join(" ");
  return [...new Set(text.match(/\{\w+\}/g) ?? [])].sort();
}

test("the privacy notice and the terms exist in every interface language", () => {
  // A player reads what they agree to in the language they read everything
  // else in (#1417); offering a language without them would hand somebody
  // English text they are held to.
  assert.deepEqual([...legalLocales()].sort(), [...LOCALES].sort());
});

test("every translation has the reference's sections, in its order", () => {
  // The ids are anchors (`/privacy#rights`): a translation that drops or
  // reorders one breaks a link written into a notice or an email.
  const reference = legalFor("en");
  for (const locale of legalLocales()) {
    const documents = legalFor(locale);
    assert.equal(documents.locale, locale);
    for (const which of DOCUMENTS) {
      assert.deepEqual(
        documents[which].sections.map((section) => section.id),
        reference[which].sections.map((section) => section.id),
        `${locale} ${which}`,
      );
    }
  }
});

test("every translation says where to write and how old to be wherever the reference does", () => {
  // A translation that lost {contact} would tell a parent of an under-age
  // player to write to nobody; an unknown token would print as itself.
  const reference = legalFor("en");
  for (const locale of legalLocales()) {
    const documents = legalFor(locale);
    for (const which of DOCUMENTS) {
      reference[which].sections.forEach((section, index) => {
        assert.deepEqual(
          placeholders(documents[which].sections[index]),
          placeholders(section),
          `${locale} ${which}#${section.id}`,
        );
      });
    }
  }
});

test("no section of any translation is empty", () => {
  for (const locale of legalLocales()) {
    const documents = legalFor(locale);
    for (const which of DOCUMENTS) {
      assert.ok(documents[which].title.trim(), `${locale} ${which} title`);
      assert.ok(documents[which].intro.every((paragraph) => paragraph.trim()));
      for (const section of documents[which].sections) {
        assert.ok(section.heading.trim(), `${locale} ${which}#${section.id} heading`);
        const text = [...section.body, ...(section.items ?? [])];
        assert.ok(text.length > 0 && text.every((line) => line.trim()), `${locale} ${which}#${section.id}`);
      }
    }
  }
});

test("a language nobody has written reads English, and a regional tag its base", () => {
  assert.equal(legalFor("ja").locale, LEGAL_FALLBACK_LOCALE);
  assert.equal(legalFor(null).locale, LEGAL_FALLBACK_LOCALE);
  assert.equal(legalFor("de-CH").locale, "de");
  assert.equal(legalFor("PT-pt").locale, "pt");
});

test("the placeholders are filled with the address and the minimum age", () => {
  assert.equal(
    legalText("Write to {contact} if you are under {age}.", "privacy@example.org"),
    `Write to privacy@example.org if you are under ${MINIMUM_AGE}.`,
  );
  assert.equal(MINIMUM_AGE, 16);
});
