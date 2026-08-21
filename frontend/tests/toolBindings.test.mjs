import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { DEFAULT_KEY_BINDINGS } from "../src/store/settingsStore.ts";

// A tool whose name does not match a KeyBindings field reads undefined and
// silently has no shortcut. TypeScript catches that now that `toolKeys` indexes
// KeyBindings directly, but only for tools it can see; this checks the toolbar's
// own list against the bindings that actually ship with keys.
const toolbar = readFileSync(new URL("../src/components/Toolbar.tsx", import.meta.url), "utf8");

function toolbarTools() {
  const block = toolbar.match(/const TOOLS: [^=]*= \[(.*?)\n\];/s);
  assert.ok(block, "TOOLS should be an array literal");
  return [...block[1].matchAll(/value:\s*"([\w]+)"/g)].map((match) => match[1]);
}

test("every tool in the toolbar has a shortcut bound by default", () => {
  for (const tool of toolbarTools()) {
    const keys = DEFAULT_KEY_BINDINGS[tool];
    assert.ok(keys, `tool "${tool}" has no entry in DEFAULT_KEY_BINDINGS`);
    assert.ok(keys.length > 0, `tool "${tool}" is bound to no keys`);
  }
});

test("the brush keeps the shortcut the pen had", () => {
  assert.deepEqual(DEFAULT_KEY_BINDINGS.brush, ["p", "1"]);
});
