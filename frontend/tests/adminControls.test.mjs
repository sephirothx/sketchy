import assert from "node:assert/strict";
import test from "node:test";

import {
  accountFragment,
  admissionLabel,
  isAdmitting,
  mergeAdmission,
  roleChangeBlocked,
  roleChangeMessage,
  roleSearchStatus,
  shutdownBlocked,
} from "../src/lib/adminControls.ts";

test("an ordinary server says it is taking rooms", () => {
  assert.equal(
    admissionLabel({ paused: false, draining: false }),
    "accepting rooms",
  );
  assert.equal(isAdmitting({ paused: false, draining: false }), true);
});

test("a paused server does not claim to be taking rooms", () => {
  // The banner is the first thing an administrator reads, and it said
  // "accepting rooms" unconditionally - the opposite of the truth during a
  // maintenance pause, which is exactly when somebody is looking at it.
  assert.equal(admissionLabel({ paused: true, draining: false }), "paused — no new rooms");
  assert.equal(isAdmitting({ paused: true, draining: false }), false);
});

test("a draining server says so, and says it before a pause", () => {
  // Both can be true at once; the drain is the one that ends the process.
  assert.equal(
    admissionLabel({ paused: true, draining: true }),
    "draining — no new rooms",
  );
  assert.equal(isAdmitting({ paused: false, draining: true }), false);
});

test("an unknown state does not assert that rooms are being taken", () => {
  // Before the first load. "accepting rooms" is the honest default only
  // because it is what an unpaused server does; the tone must not shout.
  assert.equal(admissionLabel(null), "accepting rooms");
});

test("the shutdown control refuses a click it knows will be refused", () => {
  const ok = { busy: false, maintenance: { draining: false }, reason: "deploying" };
  assert.equal(shutdownBlocked(ok), false);

  // A reason is required by the API, so an empty or token one is a 422.
  assert.equal(shutdownBlocked({ ...ok, reason: "" }), true);
  assert.equal(shutdownBlocked({ ...ok, reason: "  no  " }), true);
  // A drain already running is a 409. This is the case the confirm step used
  // to miss: it can begin after the first click, from another operator or a
  // stop sent to the host.
  assert.equal(shutdownBlocked({ ...ok, maintenance: { draining: true } }), true);
  assert.equal(shutdownBlocked({ ...ok, busy: true }), true);
  // Before the first load nothing is known; the reason still governs.
  assert.equal(shutdownBlocked({ ...ok, maintenance: null }), false);
});

test("an announcement outranks the snapshot the panel loaded", () => {
  // The loaded value is read on mount and after this panel's own commands, so
  // it is blind to a drain somebody else started - which is the case the
  // shutdown guard exists for. The announcement is broadcast at the moment the
  // state changes, so it is strictly newer.
  const loaded = { paused: false, draining: false };
  assert.deepEqual(
    mergeAdmission(loaded, { draining: true, paused: null }),
    { paused: false, draining: true },
  );
  assert.deepEqual(
    mergeAdmission(loaded, { draining: false, paused: true }),
    { paused: true, draining: false },
  );
});

test("a resume announced elsewhere clears a pause the snapshot still shows", () => {
  assert.deepEqual(
    mergeAdmission({ paused: true, draining: false }, { draining: false, paused: false }),
    { paused: false, draining: false },
  );
});

test("hearing nothing leaves the snapshot alone", () => {
  const quiet = { draining: false, paused: null };
  assert.deepEqual(
    mergeAdmission({ paused: true, draining: true }, quiet),
    { paused: true, draining: true },
  );
  // And before anything is loaded, nothing is asserted.
  assert.deepEqual(mergeAdmission(null, quiet), { paused: false, draining: false });
});

test("a drain announced elsewhere blocks the shutdown confirm", () => {
  // The whole point: the snapshot says the server is idle, the socket says it
  // is draining, and the button must believe the socket.
  const stale = { paused: false, draining: false };
  const admission = mergeAdmission(stale, { draining: true, paused: null });
  assert.equal(
    shutdownBlocked({ busy: false, maintenance: admission, reason: "deploying" }),
    true,
  );
  assert.equal(
    shutdownBlocked({ busy: false, maintenance: stale, reason: "deploying" }),
    false,
    "and would not have, without the merge",
  );
});

test("the role control refuses a click it knows will be refused", () => {
  const marta = { id: "u-1", displayName: "Marta", nameColor: null, role: "user" };
  const ok = { busy: false, selected: marta, reason: "joining the rota" };
  assert.equal(roleChangeBlocked(ok), false);

  // Nothing picked out of the list yet: the button used to act on whatever
  // string was in the box, which is how a half-pasted id became a 404.
  assert.equal(roleChangeBlocked({ ...ok, selected: null }), true);
  // A reason is required by the API, so an empty or token one is a 422.
  assert.equal(roleChangeBlocked({ ...ok, reason: "" }), true);
  assert.equal(roleChangeBlocked({ ...ok, reason: "  no  " }), true);
  assert.equal(roleChangeBlocked({ ...ok, busy: true }), true);
});

test("an administrator in the list is shown, and cannot be acted on", () => {
  // They are listed so "who holds a role now" is the whole picture, but the
  // server answers 400 - and learning that from an error message is the
  // clunkiness this control is being fixed for.
  const boss = { id: "u-2", displayName: "Operator", nameColor: null, role: "admin" };
  assert.equal(
    roleChangeBlocked({ busy: false, selected: boss, reason: "why not" }),
    true,
  );
});

test("the confirmation names the account it was about", () => {
  // "That account is now a moderator" is the feedback #507 called too thin:
  // the one thing worth confirming is which account.
  assert.equal(roleChangeMessage("Marta", "moderator"), "Marta is now a moderator.");
  assert.equal(
    roleChangeMessage("Marta", "user"),
    "Marta is no longer a moderator.",
  );
});

test("the line under the search box explains the rules the list obeys", () => {
  // An empty result is otherwise a control that has quietly declined to help.
  assert.match(
    roleSearchStatus({ query: "Marta", count: 0, failed: false }),
    /guest cannot hold a role/,
  );
  // A blank box is not "no matches" - it is who holds a role now, which is
  // the question revoking one starts from.
  assert.match(
    roleSearchStatus({ query: "  ", count: 2, failed: false }),
    /Who holds a role now/,
  );
  assert.match(
    roleSearchStatus({ query: "", count: 0, failed: false }),
    /Nobody holds a role yet/,
  );
  assert.equal(
    roleSearchStatus({ query: "Marta", count: 1, failed: false }),
    "1 account matches.",
  );
  assert.equal(
    roleSearchStatus({ query: "Mar", count: 3, failed: false }),
    "3 accounts match.",
  );
  // A failed lookup must not read as an empty one: nothing was learned.
  assert.match(
    roleSearchStatus({ query: "Marta", count: 0, failed: true }),
    /Could not search/,
  );
});

test("the id fragment tells two accounts apart, not two timestamps", () => {
  // Account ids are time-ordered, so two accounts registered in the same
  // moment share their leading half: a fragment taken from the front reads
  // identically for both, which is precisely the case it exists for.
  const first = "01a04a8f-4bfa-7289-b7f1-047530690997";
  const second = "01a04a8f-02c9-7073-9c5d-f2bd064bfbe0";
  assert.notEqual(accountFragment(first), accountFragment(second));
  assert.equal(accountFragment(first), "30690997");
});
