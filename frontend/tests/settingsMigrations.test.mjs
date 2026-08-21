import assert from "node:assert/strict";
import test from "node:test";

import {
  BRUSH_CURSOR_KEY,
  LEGACY_BRUSH_CURSOR_KEY,
  migrateKeyBindings,
  readStoredBrushCursor,
} from "../src/store/settingsMigrations.ts";
import { DEFAULT_KEY_BINDINGS } from "../src/store/settingsStore.ts";

const defaults = DEFAULT_KEY_BINDINGS;

test("a binding stored under the old name is carried onto the brush", () => {
  const migrated = migrateKeyBindings({ pen: ["b"] }, defaults);
  assert.deepEqual(migrated.brush, ["b"]);
});

test("the legacy binding does not survive into the next save", () => {
  const migrated = migrateKeyBindings({ pen: ["b"] }, defaults);
  assert.ok(!("pen" in migrated), "the retired action should be dropped, not carried");
  assert.deepEqual(Object.keys(migrated).sort(), Object.keys(defaults).sort());
});

test("a binding already stored as brush wins over the legacy one", () => {
  const migrated = migrateKeyBindings({ pen: ["b"], brush: ["k"] }, defaults);
  assert.deepEqual(migrated.brush, ["k"]);
});

test("other custom bindings are preserved and unset ones fall back", () => {
  const migrated = migrateKeyBindings({ pen: ["b"], fill: ["g"] }, defaults);
  assert.deepEqual(migrated.fill, ["g"]);
  assert.deepEqual(migrated.eraser, defaults.eraser);
});

test("junk in storage falls back to the defaults rather than throwing", () => {
  assert.deepEqual(migrateKeyBindings(null, defaults), defaults);
  assert.deepEqual(migrateKeyBindings("nonsense", defaults), defaults);
  assert.deepEqual(migrateKeyBindings({ brush: "not-an-array" }, defaults).brush, defaults.brush);
  assert.deepEqual(migrateKeyBindings({ brush: [] }, defaults).brush, defaults.brush);
  assert.deepEqual(migrateKeyBindings({ brush: [1, 2] }, defaults).brush, defaults.brush);
});

test("the brush cursor is read from the new key, then the old one", () => {
  const storage = (entries) => ({ getItem: (key) => entries[key] ?? null });
  assert.equal(readStoredBrushCursor(storage({ [BRUSH_CURSOR_KEY]: "circle" })), "circle");
  assert.equal(readStoredBrushCursor(storage({ [LEGACY_BRUSH_CURSOR_KEY]: "circle" })), "circle");
  assert.equal(
    readStoredBrushCursor(
      storage({ [BRUSH_CURSOR_KEY]: "crosshair", [LEGACY_BRUSH_CURSOR_KEY]: "circle" }),
    ),
    "crosshair",
    "a cursor set since the rename wins over the one stored before it",
  );
  assert.equal(readStoredBrushCursor(storage({})), null);
});
