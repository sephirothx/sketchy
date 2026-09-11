import assert from "node:assert/strict";
import test from "node:test";

import { announcementText, chatLineText } from "../src/lib/announcements.ts";
import { chatAnnouncement } from "../src/lib/chatAnnouncements.ts";

const line = (code, params) => ({
  id: "1",
  nickname: "",
  playerId: "",
  correct: false,
  system: true,
  code,
  params,
});

test("the room's line is built from its code and parameters", () => {
  assert.equal(
    announcementText(line("nickname_changed", { previous: "Ada", nickname: "Grace" })),
    "Ada is now known as Grace.",
  );
  assert.equal(
    announcementText(line("kicked_by_vote", { nickname: "Ada" })),
    "Ada was kicked by vote.",
  );
  assert.equal(
    announcementText(line("game_restarted_by_vote")),
    "The game was restarted by player vote.",
  );
});

test("one payload is all the server sends: the words are entirely the client's", () => {
  // The proof that the line is translatable. Nothing in the payload is a
  // sentence, so rendering it twice under two tables is the only difference
  // between two readers - which is what a second locale will be.
  const payload = line("restart_cancelled", { reason: "server_update" });
  assert.equal(payload.text, undefined);
  assert.equal(
    announcementText(payload),
    "The restart was cancelled because a server update is in progress.",
  );
  // Rendering the same payload again yields the same sentence - it holds no
  // per-reader state of its own.
  assert.equal(announcementText(payload), announcementText({ ...payload }));
});

test("a cancel reason the client has not heard of still reads as a sentence", () => {
  assert.equal(
    announcementText(line("restart_cancelled", { reason: "invented_later" })),
    "The restart was cancelled because it could no longer go ahead.",
  );
});

test("a hint line gets its own plural right", () => {
  assert.equal(
    announcementText(line("hint_letter_found", { letter: "A", cost: 5, count: 1 })),
    "'A' -5 pts - found 1 time!",
  );
  assert.equal(
    announcementText(line("hint_letter_found", { letter: "A", cost: 5, count: 3 })),
    "'A' -5 pts - found 3 times!",
  );
  assert.equal(
    announcementText(line("hint_letter_missing", { letter: "Z", cost: 5 })),
    "'Z' -5 pts - not in the prompt.",
  );
});

test("a player's own line is never translated", () => {
  const said = { id: "2", nickname: "Ada", playerId: "p1", text: "pandas", correct: false };
  assert.equal(announcementText(said), null);
  assert.equal(chatLineText(said), "pandas");
});

test("a code from a newer server renders nothing rather than a broken sentence", () => {
  const unknown = line("something_added_later", { nickname: "Ada" });
  assert.equal(announcementText(unknown), null);
  assert.equal(chatLineText(unknown), "");
});

test("a screen reader hears the room's line in the same words", () => {
  // R-A11Y-03: the live region reads the rendered sentence, not the code.
  assert.equal(
    chatAnnouncement(line("joined_as_player", { nickname: "Ada" })),
    "Ada joined as a player.",
  );
});
