import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const STYLES = join(import.meta.dirname, "../src/styles");

/* R-UX-21, in the stylesheets: a rule that sizes a text field sets 16px or
   more. The E2E walk measures the fields a screen renders; this holds the ones
   it cannot reach - a moderator's notes over a case, a staff select behind a
   filter - which is how three staff fields stayed at 13-13.5px (review of
   #1310). A field is a rule whose last compound names input, select or
   textarea, or a class ending -input, -select or -textarea. */
test("every stylesheet rule that sizes a text field sets 16px or more", () => {
  const small = [];
  for (const file of readdirSync(STYLES, { recursive: true })) {
    if (!String(file).endsWith(".css")) continue;
    const css = readFileSync(join(STYLES, String(file)), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const [, selectors, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const size = body.match(/font-size:\s*([\d.]+)px/);
      // An inherited size is whatever the parent says - 13.5px, for the
      // moderation category select under its label - so a field that takes
      // `font: inherit` says its own size too.
      const inherits = /font(-size)?:\s*inherit/.test(body) && !size;
      if (!inherits && (!size || Number(size[1]) >= 16)) continue;
      for (const selector of selectors.split(",").map((part) => part.trim())) {
        const last = selector.split(/[\s>+~]+/).at(-1) ?? "";
        if (/::?(placeholder|-webkit)/.test(last)) continue;
        if (/\[type="?(checkbox|radio|range|color|file)/.test(selector)) continue;
        if (/^(input|select|textarea)\b|-(input|select|textarea)\b/.test(last)) {
          small.push(`${file}: ${selector} ${inherits ? "inherited" : `${size[1]}px`}`);
        }
      }
    }
  }
  assert.deepEqual(small, [], `text fields under 16px:\n${small.join("\n")}`);
});
