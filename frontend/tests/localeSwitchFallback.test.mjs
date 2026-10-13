import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

// Its own file: the store and the catalogue start fresh in each process.
import { interfaceLocale, loadCatalogue } from "../src/content/ui/index.ts";
import { useSettingsStore } from "../src/store/settingsStore.ts";

// German's chunk cannot be fetched - a network drop, not a missing locale.
registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "./de.ts") throw new Error("Failed to fetch dynamically imported module");
    return next(specifier, context);
  },
});

test("a language that cannot be fetched is not a switch to English (#1426 review)", async () => {
  await loadCatalogue("it");
  assert.equal(await useSettingsStore.getState().setLocale("it"), true);
  assert.equal(interfaceLocale(), "it");
  // The fetch falls back to English. With Italian on screen that is a switch
  // that failed: the reader keeps Italian, and the caller - which saves the
  // choice to the account on success - is told so.
  assert.equal(await useSettingsStore.getState().setLocale("de"), false);
  assert.equal(interfaceLocale(), "it");
  assert.equal(useSettingsStore.getState().locale, "it");
});
