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
