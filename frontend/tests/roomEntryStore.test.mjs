import assert from "node:assert/strict";
import test from "node:test";

import { useRoomEntryStore } from "../src/store/roomEntryStore.ts";

test("one entry at a time, whoever asks", () => {
  const { begin, end } = useRoomEntryStore.getState();
  const quickPlay = begin("quick-play");
  assert.ok(quickPlay);
  assert.equal(begin("friend-invite"), null, "an invitation waits while Quick play is in flight");
  assert.equal(useRoomEntryStore.getState().pending.key, "quick-play");
  end(quickPlay);
  const invite = begin("friend-invite");
  assert.ok(invite);
  end(invite);
  assert.equal(useRoomEntryStore.getState().pending, null);
});

test("a late release cannot free somebody else's entry", () => {
  const { begin, end } = useRoomEntryStore.getState();
  const first = begin("a");
  end(first);
  const second = begin("b");
  end(first); // the first one's finally, arriving late
  assert.equal(useRoomEntryStore.getState().pending?.key, "b");
  end(second);
});
