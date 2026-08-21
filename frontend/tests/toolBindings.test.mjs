import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

// The brush tool is named "brush" but its keys are stored under `pen`, because
// the binding name is persisted. Nothing type-checks that pairing at runtime, and
// getting it wrong silently leaves the tool with no shortcut - which is exactly
// what happened once - so assert every tool resolves to real keys.
const toolbar = readFileSync(new URL("../src/components/Toolbar.tsx", import.meta.url), "utf8");
const settings = readFileSync(new URL("../src/store/settingsStore.ts", import.meta.url), "utf8");

function parseToolBindings() {
  const block = toolbar.match(/const TOOL_BINDINGS: Record<DrawTool, keyof KeyBindings> = \{([^}]*)\}/s);
  assert.ok(block, "TOOL_BINDINGS should be a total Record literal");
  return Object.fromEntries(
    [...block[1].matchAll(/(\w+):\s*"(\w+)"/g)].map((m) => [m[1], m[2]]),
  );
}

function parseDefaultBindings() {
  const block = settings.match(/export const DEFAULT_KEY_BINDINGS: KeyBindings = \{([^}]*)\}/s);
  assert.ok(block, "DEFAULT_KEY_BINDINGS should be an object literal");
  return Object.fromEntries(
    [...block[1].matchAll(/(\w+):\s*\[([^\]]*)\]/g)].map((m) => [
      m[1],
      m[2].split(",").map((k) => k.trim().replace(/"/g, "")).filter(Boolean),
    ]),
  );
}

function parseTools() {
  const block = toolbar.match(/const TOOLS: [^=]*= \[(.*?)\n\];/s);
  assert.ok(block, "TOOLS should be an array literal");
  return [...block[1].matchAll(/value:\s*"([\w]+)"/g)].map((m) => m[1]);
}

test("every tool in the toolbar resolves to a bound shortcut", () => {
  const toolBindings = parseToolBindings();
  const defaults = parseDefaultBindings();
  for (const tool of parseTools()) {
    const action = toolBindings[tool];
    assert.ok(action, `tool "${tool}" has no entry in TOOL_BINDINGS`);
    assert.ok(
      defaults[action]?.length > 0,
      `tool "${tool}" maps to "${action}", which has no default keys`,
    );
  }
});

test("the brush reads the stored `pen` binding", () => {
  assert.equal(parseToolBindings().brush, "pen");
  assert.deepEqual(parseDefaultBindings().pen, ["p", "1"]);
});
