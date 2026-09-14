import assert from "node:assert/strict";
import test from "node:test";

// apiRequest times itself out through `window`; nothing else here needs a DOM.
globalThis.window ??= globalThis;

const answers = [];
globalThis.fetch = () =>
  new Promise((resolve) => {
    answers.push((body) =>
      resolve(new Response(JSON.stringify(body), { status: 200 })),
    );
  });

const { useEmailStateStore } = await import("../src/store/emailStateStore.ts");

const PENDING = {
  address: null,
  verified: false,
  pendingAddress: "tidy@example.com",
  reminderDue: true,
  deliveryConfigured: true,
};
const CONFIRMED = {
  address: "tidy@example.com",
  verified: true,
  pendingAddress: null,
  reminderDue: false,
  deliveryConfigured: true,
};

test("an answer older than the one on screen does not bring the reminder back", async () => {
  const store = useEmailStateStore.getState();
  // The banner's read leaves with the page; the confirmation lands; the page
  // reads again. The network answers the second read first.
  const bannerRead = store.refresh("account-1");
  const afterConfirming = store.refresh();
  assert.equal(answers.length, 2);

  answers[1](CONFIRMED);
  await afterConfirming;
  answers[0](PENDING);
  await bannerRead;

  assert.deepEqual(useEmailStateStore.getState().state, CONFIRMED);
});

test("signing out forgets the address, and a read in flight does not restore it", async () => {
  answers.length = 0;
  const store = useEmailStateStore.getState();
  const inFlight = store.refresh();
  await store.refresh(null);
  answers[0](PENDING);
  await inFlight;

  assert.equal(useEmailStateStore.getState().state, null);
  assert.equal(useEmailStateStore.getState().ownerId, null);
});
