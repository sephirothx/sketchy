import assert from "node:assert/strict";
import test from "node:test";

import {
  RULES_FALLBACK_LOCALE,
  ruleAnchorFor,
  rulesFor,
  rulesLocales,
} from "../src/content/rules/index.ts";
import { REPORT_REASONS } from "../src/lib/moderation.ts";

test("every category a decision can record has a rule to link to", () => {
  // The contract behind `ruleAnchorFor`: a notice saying "recorded as spam"
  // links to #spam, and neither compiler would notice if that anchor stopped
  // existing. If a seventh reason is ever added, this is what says the rules
  // have not caught up.
  const anchored = new Set(
    rulesFor("en").sections.flatMap((section) => section.rules.map((rule) => rule.id)),
  );
  for (const reason of REPORT_REASONS) {
    assert.ok(anchored.has(reason), `no rule anchored at #${reason}`);
  }
  assert.equal(anchored.size, REPORT_REASONS.length, "a rule anchors nothing decidable");
});

test("a category's link points at its own rule", () => {
  for (const reason of REPORT_REASONS) {
    assert.equal(ruleAnchorFor(reason), `/rules#${reason}`);
  }
});

test("a language nobody has written yet still reads the rules", () => {
  // Falling back to nothing would leave a player unable to read what they are
  // held to.
  const fallback = rulesFor(RULES_FALLBACK_LOCALE);
  assert.equal(rulesFor("it").locale, fallback.locale);
  assert.equal(rulesFor(null).locale, fallback.locale);
  assert.equal(rulesFor(undefined).locale, fallback.locale);
  assert.equal(rulesFor("").locale, fallback.locale);
});

test("a regional tag reads its base language", () => {
  // `en-GB` is English; `it-CH` becomes Italian the day Italian is written,
  // without this needing to change.
  assert.equal(rulesFor("en-GB").locale, "en");
  assert.equal(rulesFor("EN-gb").locale, "en");
});

test("every locale is a complete document", () => {
  for (const locale of rulesLocales()) {
    const document = rulesFor(locale);
    assert.equal(document.locale, locale);
    assert.ok(document.title.length > 0, `${locale} has no title`);
    assert.ok(document.intro.length > 0, `${locale} has no introduction`);
    assert.ok(document.introHeading.length > 0, `${locale} has no introduction heading`);
    assert.ok(document.enforcement.body.length > 0, `${locale} says no consequence`);
    for (const section of document.sections) {
      assert.ok(section.heading.length > 0, `${locale}/${section.id} has no heading`);
      assert.ok(section.rules.length > 0, `${locale}/${section.id} has no rules`);
      for (const rule of section.rules) {
        assert.ok(rule.heading.length > 0, `${locale}/${rule.id} has no heading`);
        assert.ok(rule.body.length > 0, `${locale}/${rule.id} says nothing`);
      }
    }
  }
});
