import assert from "node:assert/strict";
import test from "node:test";

import { formatGuessTime } from "../src/lib/guessTime.ts";
import { useGameStore } from "../src/store/gameStore.ts";
import { ui } from "../src/content/ui/index.ts";

// B1: one correct guess read "0:04" in chat and the players panel, timed on
// each client's own clock, and "3.6s" on the results card, timed by the server.
// Every surface now shows the server's number, through one formatter.

test("a guess time reads in tenths under a minute", () => {
  assert.equal(formatGuessTime(3.6), "3.6s");
  assert.equal(formatGuessTime(0), "0.0s");
  assert.equal(formatGuessTime(12.04), "12.0s");
});

test("a guess time past a minute reads minutes and tenths", () => {
  assert.equal(formatGuessTime(64.3), "1:04.3");
  assert.equal(formatGuessTime(120), "2:00.0");
});

test("a guess time rounds once, so it never reads 60 seconds", () => {
  assert.equal(formatGuessTime(59.96), "1:00.0");
  assert.equal(formatGuessTime(119.97), "2:00.0");
});

test("the got-it line carries the server's time, formatted like the results card", () => {
  assert.equal(
    ui.useGameSocketListeners.gotIt({ nickname: "Ada", time: formatGuessTime(3.6), points: 120 }),
    "Ada got it · 3.6s (+120)",
  );
  assert.equal(
    ui.useGameSocketListeners.gotIt({ nickname: "Ada", time: formatGuessTime(3.6), points: null }),
    "Ada got it · 3.6s",
  );
});

test("the store keeps the server's seconds, whatever this client's clock says", () => {
  const store = useGameStore.getState();
  store.reset();
  // A phase this client believes started long ago: the old estimate would
  // have come out near 40 seconds.
  useGameStore.setState({
    phaseStartedAt: Date.now() - 40_000,
    phaseSeconds: 80,
    phaseDurationSeconds: 80,
  });
  store.recordCorrectGuess("p1", 3.6);
  store.recordCorrectGuess("p2", 11.2);
  assert.deepEqual(useGameStore.getState().turnCorrectGuesses, { p1: 3.6, p2: 11.2 });
});

test("a resync restores the same seconds correct_guess carried", () => {
  const store = useGameStore.getState();
  store.reset();
  store.startDrawing({
    drawerId: "d",
    maskedPrompt: "_ _ _",
    roundNumber: 1,
    totalRounds: 3,
    seconds: 60,
    isSync: true,
    correctGuessers: [["p1", 3.6], ["p2", 11.2]],
    guessed: null,
  });
  assert.deepEqual(useGameStore.getState().turnCorrectGuesses, { p1: 3.6, p2: 11.2 });
});
