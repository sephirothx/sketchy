import assert from "node:assert/strict";
import test from "node:test";

import {
  emailLooksUsable,
  maskEmail,
  recoveryStatusMessage,
  shouldShowRecoveryReminder,
} from "../src/lib/accountRecovery.ts";

test("an address is accepted unless it certainly cannot work", () => {
  assert.equal(emailLooksUsable("player@example.com"), true);
  assert.equal(emailLooksUsable("  player@example.co.uk "), true);
  // Deliberately permissive: the confirmation link is the real check, and
  // rejecting a valid address is worse than letting a typo through to it.
  assert.equal(emailLooksUsable("odd+tagging@sub.domain.example"), true);

  assert.equal(emailLooksUsable(""), false);
  assert.equal(emailLooksUsable("nobody"), false);
  assert.equal(emailLooksUsable("@example.com"), false);
  assert.equal(emailLooksUsable("player@"), false);
  assert.equal(emailLooksUsable("player@localhost"), false);
  assert.equal(emailLooksUsable("two words@example.com"), false);
  assert.equal(emailLooksUsable(`${"a".repeat(250)}@example.com`), false);
});

test("a confirmed address is described as the way back in, masked", () => {
  const message = recoveryStatusMessage({
    address: "player@example.com",
    verified: true,
    pendingAddress: null,
    reminderDue: false,
    deliveryConfigured: true,
  });

  // Recognisable to its owner, not readable over their shoulder: this
  // sentence rides a banner across every screen (R-SET-08).
  assert.match(message, /p••••r@e•••••e\.com/);
  assert.ok(!message.includes("player@example.com"));
});

test("an unconfirmed address says plainly that it does not count yet", () => {
  const message = recoveryStatusMessage({
    address: null,
    verified: false,
    pendingAddress: "pending@example.com",
    reminderDue: true,
    deliveryConfigured: true,
  });

  assert.match(message, /p•••••g@e•••••e\.com/);
  assert.ok(!message.includes("pending@example.com"));
  assert.match(message, /no way back in/);
});

test("a server that cannot send mail says so instead of offering a link", () => {
  const message = recoveryStatusMessage({
    address: null,
    verified: false,
    pendingAddress: null,
    reminderDue: true,
    deliveryConfigured: false,
  });

  assert.match(message, /whoever runs it/);
  assert.doesNotMatch(message, /Add an email/);
});

test("someone who already has an address is told what it is, not asked to add one", () => {
  // The dialog is reachable from the menu at any time, so it has to make sense
  // when the account is already set up - "add an email" would be a lie.
  const message = recoveryStatusMessage({
    address: "player@example.com",
    verified: true,
    pendingAddress: null,
    reminderDue: false,
    deliveryConfigured: true,
  });

  assert.match(message, /recover this account through p••••r@e•••••e\.com/);
});

const due = {
  address: null,
  verified: false,
  pendingAddress: null,
  reminderDue: true,
  deliveryConfigured: true,
};

test("the reminder stays out of a game", () => {
  // It covered the drawing tools: the room lays itself out to the viewport
  // rather than flowing beneath a banner.
  assert.equal(
    shouldShowRecoveryReminder({ registered: true, inRoom: false, dismissed: false, state: due }),
    true,
  );
  assert.equal(
    shouldShowRecoveryReminder({ registered: true, inRoom: true, dismissed: false, state: due }),
    false,
  );
});

test("a guest is never asked for a recovery address", () => {
  assert.equal(
    shouldShowRecoveryReminder({ registered: false, inRoom: false, dismissed: false, state: due }),
    false,
  );
});

test("nothing is shown before the account's state is known", () => {
  assert.equal(
    shouldShowRecoveryReminder({ registered: true, inRoom: false, dismissed: false, state: null }),
    false,
  );
});

test("an account that is already set up is left alone", () => {
  assert.equal(
    shouldShowRecoveryReminder({
      registered: true,
      inRoom: false,
      dismissed: false,
      state: { ...due, reminderDue: false, verified: true },
    }),
    false,
  );
});

test("an address is shown to its owner with one dot per hidden letter", () => {
  assert.equal(maskEmail("stefano@example.com"), "s•••••o@e•••••e.com");
  assert.equal(maskEmail("jo@example.co.uk"), "j•@e•••••e.co.uk");
  assert.equal(maskEmail("a@b.io"), "•@•.io");
  // The length is kept, so the owner can tell their addresses apart.
  assert.equal(maskEmail("stefano@example.com").length, "stefano@example.com".length);
});

test("masking keeps the shape of anything that is not quite an address", () => {
  // No @, a trailing @, or a domain with no dot: still never printed whole.
  assert.equal(maskEmail("nonsense"), "n••••••e");
  assert.equal(maskEmail("trailing@"), "t•••••••@");
  assert.equal(maskEmail("someone@localhost"), "s•••••e@l•••••••t");
});

test("masking reveals neither the local part nor the domain label", () => {
  for (const address of ["stefano@example.com", "jo@example.co.uk", "a@b.io"]) {
    const [local, domain] = address.split("@");
    const masked = maskEmail(address);
    assert.ok(!masked.includes(local), `${masked} still contains ${local}`);
    assert.ok(
      !masked.includes(domain.split(".")[0]),
      `${masked} still contains the domain label`,
    );
  }
});
