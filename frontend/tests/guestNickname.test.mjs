import assert from "node:assert/strict";
import test from "node:test";

import { needsGuestNickname, registeredNicknameTakenMessage, resolvedPlayName, isValidGuestNickname, GUEST_NICKNAME_RULES_MESSAGE } from "../src/lib/guestNickname.ts";

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
  assert.equal(resolvedPlayName("Cool Cat", guest), "");
  assert.equal(resolvedPlayName("", { ...namedGuest, displayName: "Cool Cat" }), "");
});

test("needsGuestNickname is true only until a guest has a name", () => {
  assert.equal(needsGuestNickname("", guest), true);
  assert.equal(needsGuestNickname("Ada", guest), false);
  assert.equal(needsGuestNickname("", namedGuest), false);
  assert.equal(needsGuestNickname("", registered), false);
  assert.equal(needsGuestNickname("Cool Cat", guest), true);
});

test("guest nicknames use the same charset as usernames", () => {
  assert.equal(isValidGuestNickname("Ada"), true);
  assert.equal(isValidGuestNickname("Cool_Cat"), true);
  assert.equal(isValidGuestNickname("Cool Cat"), false);
  assert.equal(isValidGuestNickname("ab"), false);
  assert.equal(
    GUEST_NICKNAME_RULES_MESSAGE,
    "Nickname must be 3-16 characters and contain only letters, digits, underscores, or hyphens",
  );
});

test("registeredNicknameTakenMessage matches the server copy", () => {
  assert.equal(
    registeredNicknameTakenMessage("BobUser"),
    "The nickname 'BobUser' is already taken by a registered account",
  );
});
