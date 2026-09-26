import assert from "node:assert/strict";
import test from "node:test";

import { useFriendInviteStore } from "../src/store/friendInviteStore.ts";

const invite = (name) => ({ fromUserId: `id-${name}`, displayName: name, inviteToken: `t-${name}`, expiresIn: 120 });

test("a newer invitation replaces the older, and answering clears it", () => {
  const { receive, clear } = useFriendInviteStore.getState();
  receive(invite("Ada"));
  receive(invite("Bob"));
  assert.equal(useFriendInviteStore.getState().invite.displayName, "Bob");
  clear();
  assert.equal(useFriendInviteStore.getState().invite, null);
});

test("the card steps aside while any room bar holds the invitation (#1176)", () => {
  const { claimRoomBar } = useFriendInviteStore.getState();
  assert.equal(useFriendInviteStore.getState().roomBarClaims, 0);
  const first = claimRoomBar();
  const second = claimRoomBar();
  first();
  // A cleanup that runs twice (StrictMode, a remount) must not hand the card
  // back while the other bar is still up.
  first();
  assert.equal(useFriendInviteStore.getState().roomBarClaims, 1);
  second();
  assert.equal(useFriendInviteStore.getState().roomBarClaims, 0);
});
