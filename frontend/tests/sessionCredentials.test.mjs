import assert from "node:assert/strict";
import test from "node:test";

import {
  clearReconnectSecret,
  readReconnectSecret,
  writeReconnectSecret,
} from "../src/lib/sessionCredentials.ts";

function memoryStorage(entries = []) {
  const values = new Map(entries);
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    values,
  };
}

test("legacy public player IDs are discarded instead of used as reconnect secrets", () => {
  const storage = memoryStorage([["sketchy_token_ABC123", "public-player-id"]]);

  assert.equal(readReconnectSecret(storage, "ABC123"), null);
  assert.equal(storage.values.has("sketchy_token_ABC123"), false);
});

test("private reconnect secrets use a separate key and clear legacy state", () => {
  const storage = memoryStorage([["sketchy_token_ABC123", "legacy"]]);

  writeReconnectSecret(storage, "ABC123", "private-secret");
  assert.equal(readReconnectSecret(storage, "ABC123"), "private-secret");

  clearReconnectSecret(storage, "ABC123");
  assert.equal(readReconnectSecret(storage, "ABC123"), null);
});
