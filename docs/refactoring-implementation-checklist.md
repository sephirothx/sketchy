# Refactoring Implementation Checklist

This checklist turns the recommendations in
[`refactoring-proposals.md`](refactoring-proposals.md) and GitHub issues
[#228](https://github.com/sephirothx/sketchy/issues/228) through
[#233](https://github.com/sephirothx/sketchy/issues/233) into an implementation order.

The order is dependency-driven: establish reliable CI first, fix security and correctness
defects before moving their code, create stable domain boundaries, and only then split the
large modules. Testing is part of every step rather than a final cleanup phase.

## Working agreement

- [ ] Use one pull request per numbered step unless a step is explicitly divided below.
- [ ] Keep behavior-preserving moves separate from behavior changes where practical.
- [ ] Add regression tests before or with every defect fix.
- [ ] Run the focused tests while developing and the full relevant suite before merging.
- [ ] Keep each intermediate commit deployable; do not leave two competing owners for state.
- [ ] Update this checklist and the linked issue when scope or an invariant changes.

## 0. Record the baseline

- [x] Run and record the current backend suite: `cd backend && .venv/bin/pytest -q`.
- [x] Run and record the current frontend checks: `cd frontend && npm test && npm run lint && npm run build`.
- [x] Run `./scripts/test-e2e.sh` once in a known-good environment.
- [x] Record the existing canvas benchmark results with `./benchmarks/run_canvas.sh`.
- [x] Note existing failures separately so later refactors are not blamed for them.

**Exit gate:** the team has a reproducible baseline for correctness and canvas performance.

## 1. Strengthen CI and E2E startup diagnostics — issue #230

- [x] Add `npm test` to the frontend CI job before lint and build.
- [x] Poll `/api/health` in `scripts/test-e2e.sh` instead of the SPA root.
- [x] Detect when the background server exits during startup polling.
- [x] Exit with one concise diagnostic if the server never becomes healthy.
- [x] Confirm Playwright is not launched after a startup failure.
- [x] Verify the normal successful E2E path is unchanged.
- [x] Merge and close [#230](https://github.com/sephirothx/sketchy/issues/230).

**Why first:** every later change depends on frontend protocol tests actually blocking a bad
merge and on E2E failures being actionable.

## 2. Separate public player identity from reconnect credentials — issue #231

- [x] Add a public, broadcastable player ID distinct from the reconnect secret.
- [x] Audit room state, chat, score, vote, recap, and preview payloads for secret exposure.
- [x] Ensure reconnect secrets are returned only to the player who owns them.
- [x] Introduce `require_current_player(sid)` or an equivalent centralized authorization helper.
- [x] Require the caller's SID to match the player's current active SID for every authenticated command.
- [x] Define and implement how a successful reconnect supersedes the old socket.
- [x] Update frontend types and local credential storage, including legacy-value handling.
- [x] Add tests for host and player impersonation, stale sockets, valid reconnects, and payload secrecy.
- [x] Update the README's reconnect/session documentation.
- [x] Merge and close [#231](https://github.com/sephirothx/sketchy/issues/231).

**Exit gate:** public identifiers are safe to broadcast, reconnect secrets remain private, and
superseded sockets cannot act for a player.

## 3. Bound guess processing — issue #233

- [x] Define shared backend limits for guesses and chat messages.
- [x] Reject oversized input before normalization, matching, edit distance, or broadcast.
- [x] Skip close-guess calculation when the length difference already exceeds the useful distance.
- [x] Replace the full edit-distance matrix with a bounded/banded or rolling-row implementation.
- [x] Preserve valid close-guess and transposition behavior.
- [x] Add boundary and adversarial-input tests.
- [x] Add a focused benchmark or memory-oriented test for the largest accepted input.
- [x] Defer per-socket guess rate limiting to a follow-up; it is a separate gameplay policy,
  while the input and edit-distance bounds close the resource-exhaustion path in this issue.
- [x] Merge and close [#233](https://github.com/sephirothx/sketchy/issues/233).

**Why before broad validation:** this is a focused resource-exhaustion fix and should not wait
for every Socket.IO command to receive a typed request model.

## 4. Correct moderation eligibility — issue #232

- [x] Document whether AFK players and the target count toward the voting population.
- [x] Reject votes cast by spectators on the backend.
- [x] Decide and enforce whether spectators may be vote targets.
- [x] Calculate thresholds from the documented set of connected, eligible players.
- [x] Make the frontend display the exact population and threshold enforced by the backend.
- [x] Add tests for spectator voters, spectator population changes, AFK cases, and ordinary votes.
- [x] Add a direct-socket regression test rather than relying only on disabled UI controls.
- [ ] Merge and close [#232](https://github.com/sephirothx/sketchy/issues/232).

**Dependency:** use the centralized current-player authorization introduced in step 2.

## 5. Own and clean up asynchronous timers — issue #229

- [ ] Introduce the application-owned `TimerManager` described in proposal 1.
- [ ] Move phase, hint-checkpoint, and disconnect task registries into it.
- [ ] Remove naturally completed tasks from their registries.
- [ ] Guard cleanup by task identity so an old task cannot remove its replacement.
- [ ] Cancel tasks when their room/player lifecycle ends.
- [ ] Add application-shutdown cleanup that cancels and awaits outstanding tasks.
- [ ] Test natural completion, cancellation, replacement races, repeated disconnects, and shutdown.
- [ ] Merge and close [#229](https://github.com/sephirothx/sketchy/issues/229).

**Exit gate:** no completed task is retained indefinitely and lifecycle cleanup has one owner.

## 6. Validate every Socket.IO command at the boundary — issue #228

- [ ] Inventory every client-originated command and document its request shape.
- [ ] Add focused typed request models or parsers under `handlers/payloads.py`.
- [ ] Reject non-object payloads consistently.
- [ ] Define explicit string, boolean, enum, and integer coercion policies.
- [ ] Reject booleans as integers and bound numeric and string inputs.
- [ ] Standardize acknowledged validation failures as `{ ok: false, error, ... }`.
- [ ] Ensure validation completes before any domain mutation or broadcast.
- [ ] Migrate commands incrementally while keeping shared error behavior consistent.
- [ ] Test malformed objects, missing fields, invalid numerics, oversized strings, and no-partial-mutation behavior.
- [ ] Merge and close [#228](https://github.com/sephirothx/sketchy/issues/228).

**Dependency:** reuse the authorization and length-limit policies established in steps 2 and 3;
do not create a competing authentication or guess-validation path.

## 7. Extract the backend `CanvasSession` domain boundary — proposal 3

- [ ] Add direct characterization tests for current canvas history, revision, hash, and reset behavior.
- [ ] Add versioned cross-language golden fixtures for frames, histories, CRC32 hashes, and malformed versions.
- [ ] Introduce `CanvasSession` as the owner of drawing history, revision, hash, and generation identity.
- [ ] Keep the monotonic canvas-generation allocator on `Room`.
- [ ] Update callers to use `game.canvas` explicitly; avoid compatibility delegation properties.
- [ ] Keep scoring, words, players, rounds, and turn progression on `Game`.
- [ ] Add `test_canvas_session.py` and run backend protocol tests after each call-site migration.

**Exit gate:** `Game` no longer owns canvas protocol internals and generation has one source of truth.

## 8. Extract pure frontend canvas modules — first half of proposal 4

- [ ] Capture a benchmark and browser performance profile before changing hot paths.
- [ ] Extract pure geometry helpers into `canvasGeometry.ts`.
- [ ] Extract typed-array rasterization, color matching, and flood fill into `canvasPixels.ts`.
- [ ] Extract imperative drawing operations into `canvasRenderer.ts`.
- [ ] Add Node tests for geometry and pixel operations without requiring a DOM canvas.
- [ ] Compare benchmark output and Chrome DevTools profiles before and after extraction.
- [ ] Keep protocol state and pointer ownership unchanged during this step.

**Exit gate:** pure algorithms are independently testable and performance has not materially regressed.

## 9. Split the room-entry and active-room UI — proposal 2

- [ ] Characterize invite preview, reconnect, direct join, spectator join, and stale-response behavior.
- [ ] Extract the framework-independent room-entry state machine and `useRoomEntry` adapter.
- [ ] Extract `InviteEntryPage` and `ActiveGameRoom`.
- [ ] Extract `useToolbarState` while preserving turn-safe render-time reset semantics.
- [ ] Retain the `activeRoomId` guard so a stored session from another room is not reused.
- [ ] Add tests for valid/expired credentials, cancellation, stale responses, and join modes.
- [ ] Verify desktop and mobile layouts manually or with screenshots.

**Exit gate:** `GameRoomPage` is a thin entry/active router and asynchronous entry state has one owner.

## 10. Split backend Socket.IO handlers — proposal 1

- [ ] Introduce `HandlerContext` and make `register_all_handlers` return it for lifecycle cleanup.
- [ ] Add `GameFlowService` for workflows shared across handler domains.
- [ ] Add pure payload construction in `presenters.py`; keep emitting in handlers/services.
- [ ] Move handlers one domain at a time: moderation, rooms, chat, drawing, game, then connection.
- [ ] Keep handler implementations as directly testable top-level functions.
- [ ] Prevent handler modules from importing one another.
- [ ] Split `test_events.py` into focused handler suites as each group moves.
- [ ] Delete `events.py` only after all registrations and tests have migrated.
- [ ] Wire `TimerManager.close()` into the ASGI application lifecycle.

**Dependencies:** steps 2, 5, and 6 supply the authentication, timer, and validation boundaries;
step 7 supplies the canvas boundary. This step should primarily move already-correct code.

## 11. Extract frontend canvas protocol and pointer ownership — second half of proposal 4

- [ ] Introduce one `useCanvasProtocol` owner for authoritative history, socket listeners, synchronization, ordered commits, recovery, and replay.
- [ ] Introduce `useCanvasPointerInput` for pointer capture, batching, finalization, and cancellation.
- [ ] Keep `Canvas.tsx` as the composition/rendering surface rather than a second protocol owner.
- [ ] Keep recap rendering in a separate read-only `CanvasSnapshot` component.
- [ ] Expose narrow commands and derived state instead of broad mutable refs.
- [ ] Add protocol tests for stale generations, mismatched hashes, reconnect sync, and pending replay.
- [ ] Run the cross-language fixtures, full E2E suite, benchmark, and desktop/mobile browser profiles.

**Exit gate:** history, mutations, socket synchronization, and replay have exactly one frontend owner.

## 12. Modularize CSS — proposal 5

- [ ] Add explicit cascade layers in the order `reset`, `theme`, `layout`, `components`, `utilities`.
- [ ] Move rules into screen/component stylesheets without changing selectors or specificity first.
- [ ] Keep tokens, resets, and genuinely global primitives in global files.
- [ ] Use CSS Modules only for later changes or new components; do not mix scoping changes into the mechanical split.
- [ ] Compare screenshots across supported themes, desktop/mobile breakpoints, overlays, and game phases.
- [ ] Remove obsolete selectors only in a follow-up cleanup after the split is stable.

**Exit gate:** styles are navigable by domain, cascade order is explicit, and visual behavior is unchanged.

## Final verification

- [ ] Run `cd backend && .venv/bin/pytest -q`.
- [ ] Run `cd frontend && npm test && npm run lint && npm run build`.
- [ ] Run `./scripts/test-e2e.sh` across the supported browsers.
- [ ] Run `./benchmarks/run_canvas.sh` and compare with the step 0 baseline.
- [ ] Confirm cross-language protocol fixtures pass in both Python and TypeScript.
- [ ] Confirm issues #228–#233 are closed with links to their regression tests.
- [ ] Update `README.md` and `refactoring-proposals.md` to match the final structure.
- [ ] Remove this checklist or convert any remaining unchecked work into focused follow-up issues.
