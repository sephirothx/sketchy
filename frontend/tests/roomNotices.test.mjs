import assert from "node:assert/strict";
import test from "node:test";

import { kickedText, supersededText } from "../src/lib/roomNotices.ts";
import { catalogueFor, setCatalogue } from "../src/content/ui/index.ts";

test("a removal is said from its code, never from the server's reason", () => {
  setCatalogue("en");
  assert.equal(kickedText("kicked_by_vote"), "You were kicked from the room by vote.");
  assert.equal(kickedText("room_closed"), "An administrator closed this room.");
  assert.equal(kickedText("removed_by_admin"), "An administrator removed you.");
  assert.equal(supersededText("account_deleted"), "Your account was deleted.");
  assert.equal(supersededText("opened_elsewhere"), "This room was opened in another tab.");
});

test("a code this build does not know gets the general sentence", () => {
  setCatalogue("en");
  assert.equal(kickedText("from_a_newer_server"), "You were kicked from the room.");
  assert.equal(kickedText(undefined), "You were kicked from the room.");
  assert.equal(supersededText(undefined), "This room was opened in another tab.");
});

test("the sentence follows the reader's language", () => {
  setCatalogue("de");
  try {
    assert.equal(kickedText("kicked_by_vote"), catalogueFor("de").roomNotices.kickedByVote);
    assert.notEqual(kickedText("kicked_by_vote"), catalogueFor("en").roomNotices.kickedByVote);
  } finally {
    setCatalogue("en");
  }
});
