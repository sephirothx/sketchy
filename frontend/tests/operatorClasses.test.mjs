import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = join(import.meta.dirname, "../src");

/* Every ops- class the staff pages name has a rule. Two of the seven Controls
   cards named `ops-card-note`, which no stylesheet defines, and set their
   note as full-width body text (#1280). Scoped to the ops- prefix: elsewhere
   a class is as often a test's handle as a style's. */
test("every ops- class in the staff pages has a rule in operator.css", () => {
  const css = readFileSync(join(SRC, "styles/operator.css"), "utf8");
  const defined = new Set([...css.matchAll(/\.(ops-[a-z0-9-]+)/g)].map((match) => match[1]));
  const missing = [];
  for (const file of readdirSync(SRC, { recursive: true })) {
    if (!/\.tsx?$/.test(String(file))) continue;
    const source = readFileSync(join(SRC, String(file)), "utf8");
    for (const [, list] of source.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g).map((m) => [m, m[1] ?? m[2]])) {
      for (const name of list.split(/\s+/)) {
        if (/^ops-[a-z0-9-]+$/.test(name) && !defined.has(name)) missing.push(`${file}: ${name}`);
      }
    }
  }
  assert.deepEqual(missing, [], `ops- classes with no rule:\n${missing.join("\n")}`);
});
