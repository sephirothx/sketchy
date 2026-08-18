import assert from "node:assert/strict";
import test from "node:test";

import { needsGuestNickname, registeredNicknameTakenMessage, resolvedPlayName } from "../src/lib/guestNickname.ts";

const guest = {
  id: "u1",
  username: null,
  displayName: "Guest",
  nameColor: null,
  avatarUrl: null,
  isAnonymous: true,
  createdAt: "",
  lastLoginAt: "",
};

const namedGuest = { ...guest, displayName: "Ada" };
const registered = { ...guest, isAnonymous: false, username: "Ada", displayName: "Ada" };

test("resolvedPlayName prefers a stored guest nickname", () => {
  assert.equal(resolvedPlayName("Ada", guest), "Ada");
  assert.equal(resolvedPlayName("", namedGuest), "Ada");
  assert.equal(resolvedPlayName("", guest), "");
  assert.equal(resolvedPlayName("", registered), "Ada");
});

test("needsGuestNickname is true only until a guest has a name", () => {
  assert.equal(needsGuestNickname("", guest), true);
  assert.equal(needsGuestNickname("Ada", guest), false);
  assert.equal(needsGuestNickname("", namedGuest), false);
  assert.equal(needsGuestNickname("", registered), false);
});

test("registeredNicknameTakenMessage matches the server copy", () => {
  assert.equal(
    registeredNicknameTakenMessage("BobUser"),
    "The nickname 'BobUser' is already taken by a registered account",
  );
});
