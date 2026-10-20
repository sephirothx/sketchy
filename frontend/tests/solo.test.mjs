import assert from "node:assert/strict";
import test from "node:test";

import { decodeSoloForms } from "../src/lib/solo.ts";

test("the client reads the forms the server encoded (#1434)", () => {
  // Encoded by `encode_answers` in backend/app/solo_rules.py.
  const serveId = "01a14074-b2c3-7d4e-8f90-0a1b2c3d4e5f";
  const encoded =
    "eoMsFdykCC/o9SghDB8qOiONYFbdtBNstbBxOVxPITJx1WJOkuE1jTPkfn4OEW59YM0pFcGmDmy1sFFGURFufW7VKBHAsF90r+sofkIfdH96gzAG3a4NOq2qKjlESDp9LYFiFd6qHD3q4yghDGZsLGnAIx+QngAzo7Aob01WKzEjm2AvkKsIOq3Ndw==";
  assert.deepEqual(decodeSoloForms(serveId, encoded), {
    language: "de",
    own: { prompt: "Hütte", aliases: [] },
    others: { en: { prompt: "hut", aliases: ["shack"] } },
    taken: ["hut"],
  });
});

test("the Daily's date is the player's own calendar day", async () => {
  const { localDateKey } = await import("../src/lib/solo.ts");
  assert.equal(localDateKey(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
  assert.equal(localDateKey(new Date(2026, 9, 15, 0, 0)), "2026-10-15");
});

test("Solo's page copy is written in every interface language, none of it blank", async () => {
  const { soloCopyFor, soloCopyLocales } = await import("../src/content/solo/index.ts");
  const { LOCALES } = await import("../src/content/ui/index.ts");
  assert.deepEqual([...soloCopyLocales()].sort(), [...LOCALES].sort());
  const sample = { played: 2, points: 120, count: 3, days: 2, time: "01:00:00", position: 1, length: 5,
    seconds: 9, guess: "x", solved: 1, total: 5, daily: "Daily", date: "2026-10-15", marks: "🟩", goal: 7,
    left: 3, name: "Quick", status: "Done", action: "Review", prompt: "cat" };
  for (const locale of soloCopyLocales()) {
    for (const [key, value] of Object.entries(soloCopyFor(locale))) {
      const text = typeof value === "function" ? value(sample) : value;
      assert.ok(typeof text === "string" && text.trim(), `${locale}.${key} is blank`);
      // A parameter the sample lacks would read as NaN or undefined, and pass
      // as not blank.
      assert.doesNotMatch(text, /NaN|undefined/, `${locale}.${key} reads a parameter the sample lacks`);
    }
  }
  assert.equal(soloCopyFor("pt-BR"), soloCopyFor("pt"), "a regional tag reads its base");
  assert.equal(soloCopyFor("xx"), soloCopyFor("en"));
});
