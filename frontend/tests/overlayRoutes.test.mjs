import assert from "node:assert/strict";
import test from "node:test";

import {
  FRIENDS_PATH,
  isFriendsPath,
  isOverlayPath,
  isSettingsPath,
  overlayBackgroundOf,
} from "../src/lib/overlayRoutes.ts";

// The one thing App.tsx cannot get wrong quietly: an overlay path it does not
// recognise renders the page table against the overlay's own location, so the
// overlay draws over the not-found page instead of the room it was opened
// from - and nothing throws.
test("every overlay path is recognised as one", () => {
  for (const path of ["/settings", "/settings/account", FRIENDS_PATH, "/friends/"]) {
    assert.equal(isOverlayPath(path), true, path);
  }
});

test("an ordinary page is not an overlay", () => {
  for (const path of ["/", "/create", "/room/ABC123", "/profile/9", "/settingsy"]) {
    assert.equal(isOverlayPath(path), false, path);
  }
});

// react-router matches case-insensitively unless a route sets caseSensitive,
// and none of ours do - so /Friends draws the overlay and has to be treated
// as one here too.
test("overlay paths are matched the way react-router matches them", () => {
  assert.equal(isSettingsPath("/Settings/Account"), true);
  assert.equal(isFriendsPath("/FRIENDS"), true);
});

test("the two overlays do not claim each other's paths", () => {
  assert.equal(isFriendsPath("/settings"), false);
  assert.equal(isSettingsPath("/friends"), false);
});

test("a background is read only when it is a usable path", () => {
  assert.equal(overlayBackgroundOf({ overlayBackground: "/room/ABC123" }), "/room/ABC123");
  // Everything a history entry can actually hold. Each of these means "came
  // here directly", and the caller draws the lobby behind them.
  for (const state of [null, undefined, {}, { overlayBackground: "" }, { overlayBackground: 7 }, "not-an-object"]) {
    assert.equal(overlayBackgroundOf(state), null, JSON.stringify(state ?? null));
  }
});
