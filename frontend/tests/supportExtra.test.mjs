import assert from "node:assert/strict";
import test from "node:test";

import { euroSignFirst, extraTypedAllowed, formatPaid } from "../src/lib/support.ts";

test("the extra's box takes amounts as they are typed, and nothing else", () => {
  for (const typed of ["", "5", "12", "7.", "7,5", "7.50", ".5", "500"]) {
    assert.equal(extraTypedAllowed(typed, 50_000), true, typed);
  }
  for (const typed of ["$69", "€5", "5€", "abc", "1e3", "-5", "5.555", "1.2.3", "5 ", "500.01", "501"]) {
    assert.equal(extraTypedAllowed(typed, 50_000), false, typed);
  }
});

test("the euro sign goes where the page's language writes it", () => {
  // Portuguese is left out: whichever side it lands on is the runtime's call.
  assert.equal(euroSignFirst("en"), true);
  assert.equal(euroSignFirst("nl"), true);
  for (const lang of ["de", "fr", "es", "it", "pl"]) {
    assert.equal(euroSignFirst(lang), false, lang);
  }
});

test("an amount paid is shown in its own currency's units", () => {
  assert.equal(formatPaid(2650, "EUR", "en"), "€26.50");
  assert.equal(formatPaid(2650, "JPY", "en"), "¥2,650");
});
