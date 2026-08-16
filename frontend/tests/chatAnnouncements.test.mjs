import assert from "node:assert/strict";
import test from "node:test";

import { chatAnnouncement } from "../src/lib/chatAnnouncements.ts";

test("announces correct guesses without exposing the word", () => {
  assert.equal(
    chatAnnouncement({
      id: "1",
      nickname: "Ada",
      text: "banana",
      correct: true,
    }),
    "Ada guessed the word.",
  );
});

test("announces system messages", () => {
  assert.equal(
    chatAnnouncement({
      id: "2",
      nickname: "Sketchy",
      text: "Bob joined the room.",
      correct: false,
      system: true,
    }),
    "Bob joined the room.",
  );
});

test("never announces restricted guesses", () => {
  assert.equal(
    chatAnnouncement({
      id: "3",
      nickname: "Ada",
      text: "secret",
      correct: false,
      restricted: true,
    }),
    null,
  );
});

test("ignores ordinary chat and close hints", () => {
  assert.equal(
    chatAnnouncement({
      id: "4",
      nickname: "Ada",
      text: "hello",
      correct: false,
    }),
    null,
  );
  assert.equal(
    chatAnnouncement({
      id: "5",
      nickname: "Sketchy",
      text: "close!",
      correct: false,
      close: true,
    }),
    null,
  );
});
