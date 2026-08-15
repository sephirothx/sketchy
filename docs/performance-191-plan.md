# Performance Epic #191: Implementation Plan

## Objective

Finish the remaining canvas-performance work without carrying forward stale
assumptions from the original epic. Preserve drawing and replay semantics, use
measurements to decide whether architectural work is warranted, and close
issues whose original problems no longer exist.

## Agreed issue disposition

- [x] **#149 — Keep and implement.** Replace the per-pixel eight-neighbour
  flood-fill stack with a lower-allocation scanline/span implementation while
  preserving eight-connectivity, colour tolerance, and deterministic replay.
- [x] **#123 — Rewrite and measure first.** Re-scope it to synchronous
  interactive canvas readback and rasterization. Do not prescribe
  `requestAnimationFrame`, `OffscreenCanvas`, or a worker until profiling shows
  where time is spent.
- [x] **#189 — Replace the original scope with a bounded residual analysis.**
  The compact semantic history and incremental Undo work have addressed most
  of the original risk. Measure worst-case reconnect, late-join, and replay
  behaviour before deciding whether checkpoints are justified.
- [x] **#185 — Close as obsolete/resolved.** Round transitions no longer encode
  a PNG synchronously; `toDataURL` is used only for an explicit download.
- [x] **#150 — Close as not planned.** A persistent replay canvas retains an
  approximately 1.9 MB pixel backing store to avoid an infrequent allocation.
  Reconsider only if allocation profiling demonstrates meaningful GC pressure.

## Constraints

- [x] Preserve the current 800×600 rendered output and quarter-pixel coordinate
  semantics.
- [x] Preserve eight-connected flood fill and
  `FLOOD_FILL_CHANNEL_TOLERANCE` behaviour.
- [x] Preserve cross-browser deterministic replay, including Chromium and Firefox.
- [x] Keep Undo as a compact incremental protocol operation.
- [x] Treat checkpoints as an outcome of measurement, not a predetermined design.
- [x] Do not use machine-specific timing assertions in the regular test suite.

## Phase 1: Establish baselines

- [x] Run the existing desktop and throttled-mobile browser benchmark.
- [x] Save the raw results with the tested commit, browser versions, and machine
  details.
- [x] Record drawer-to-observer stroke latency, large-fill latency,
  Undo/replay latency, retained action count, and `sync_strokes` bytes.
- [x] Add a local-drawer measurement for pointer handling and rasterization;
  the existing network latency measurement does not isolate local rendering.
- [x] Capture a DevTools performance trace for:
  - [x] a full-canvas fill;
  - [x] a fill inside a complex boundary;
  - [x] a fast pen/eraser stroke;
  - [x] repeated Undo operations.
- [x] Capture allocation samples across large fills and repeated replay.
- [x] Record separate `getImageData` and `putImageData` calls/time, pixels read,
  interaction-handler time, heap deltas, and replay-canvas creation counts.
- [x] Capture pixel-processing tasks and garbage-collection events in the raw
  DevTools timeline traces for follow-up comparison.

Baseline results and run metadata are recorded in
`docs/performance-191-baseline.md`; raw JSON, DevTools traces, and heap profiles
are stored alongside it under `docs/`.

## Phase 2: Implement #149

### Tests first

- [x] Add a diagonal-only fixture proving eight-connected behaviour.
- [x] Retain tests for no-op fills, canvas boundaries, and colour tolerance.
- [x] Add fixtures containing narrow passages, isolated islands, alternating
  rows, and irregular complex boundaries.
- [x] Add a large-area correctness test that compares the resulting pixels with
  the current implementation or a frozen expected result.
- [x] Confirm deterministic, pixel-equivalent fills against the previous
  eight-neighbour implementation across 40 generated fixtures.

### Implementation

- [x] Implement an eight-connected scanline/span fill in
  `frontend/src/lib/canvasPixels.ts`.
- [x] Avoid a dynamically growing stack containing eight coordinate pairs for
  every visited pixel.
- [x] Keep bounds checking and tolerance matching explicit.
- [x] Keep the function's boolean no-op/result contract unchanged.
- [x] Document the fixed 480 KB status buffer and at-most-once seed queue.

### Verification gate

- [x] Run frontend unit tests, lint, and the production build.
- [x] Run the canvas benchmark on desktop and throttled mobile.
- [x] Compare main-thread duration, peak allocation, and GC activity with the
  Phase 1 baseline.
- [x] Confirm no meaningful regression in stroke or Undo/replay latency with a
  second benchmark run.
- [x] Acceptance gate met: correctness is unchanged, full-fill latency improved
  by approximately 79%, and transient heap growth fell by approximately 97%.

Detailed results are recorded in `docs/performance-191-phase2.md`.

## Phase 3: Re-scope and evaluate #123

### Rewrite the issue

- [x] Remove references to React pointer-move state updates already resolved by
  #147.
- [x] Remove claims that multi-segment observer rasterization is still missing;
  #148 addressed that path.
- [x] Point the issue at `useCanvasPointerInput.ts` and `canvasRenderer.ts`, not
  the former monolithic implementation in `Canvas.tsx`.
- [x] State the remaining question: whether synchronous bounded-region
  `getImageData`/`putImageData` causes visible local drawing stalls.
- [x] Make the acceptance criteria measurement-based and include local input
  latency, frame time, and pixel-equivalent output.

### Decision gate

- [x] Count canvas readbacks and total readback/rasterization time during a
  representative fast stroke.
- [x] Test desktop and throttled-mobile profiles.
- [x] No material local stall was observed; close #123 as superseded by
  #147/#148 and record the measurements.
- [x] Do not enter the implementation branch: the throttled-mobile local
  handler remained at 5.4 ms p95, while median readback and upload together
  consumed 0.3 ms.
- [x] Skip comparison of pointer-sample coalescing, a retained CPU surface,
  worker-backed `OffscreenCanvas`, and reduced readback frequency because the
  measurement gate was not crossed.
- [x] Preserve the existing pixel-equivalent renderer and deterministic replay;
  no implementation-specific regression coverage is required.

The measurements and decision are recorded in
`docs/performance-191-phase3.md`.

## Phase 4: Replace the residual scope of #189

### Document what is already complete

- [x] Link #197: semantic path, shape, and fill history.
- [x] Link #199: packed binary history and binary synchronization.
- [x] Link #207: client-side cached history and incremental Undo.
- [x] Link #208: acknowledged mutations, sequence recovery, and history hashes.
- [x] Record that normal Undo no longer transfers the complete history.
- [x] Record the existing `MAX_CANVAS_ACTIONS` and `MAX_CANVAS_POINTS` bounds.

### Add worst-case measurements

- [x] Add deterministic path-heavy, shape-heavy, fill-heavy, and mixed fixtures
  near the accepted action/point limits.
- [x] Measure packed server memory, encoded `sync_strokes` bytes, decode time,
  and complete browser replay time.
- [x] Verify the theoretical maximum binary history size with an automated test
  rather than relying only on representative drawings.
- [x] Measure late join and reconnect on desktop and throttled mobile.
- [x] Measure repeated fill replay separately, because a small encoded fill can
  still require a full-canvas pixel traversal.
- [x] Audit all per-turn protocol state, including the `commits` list, for a
  documented bound or safe pruning strategy.

### Architecture decision

- [x] Agree on acceptable payload, replay-time, and per-room-memory budgets.
- [x] Confirm payload, server state, encode/decode, and path/shape replay stay
  within budget; record that fill-heavy and mixed replay exceed the accepted
  full-history replay budget.
- [x] Open focused follow-up #257 for the failing replay-work dimension rather
  than restoring the original broad scope.
- [x] Make raster checkpoints plus semantic deltas eligible only because replay
  is now the demonstrated bottleneck; do not predetermine them over a simpler
  weighted replay-work bound.
- [x] Require #257 to preserve Undo depth and deterministic late-join
  reconstruction.

Detailed measurements and the budget decision are recorded in
`docs/performance-191-phase4.md`.

## Phase 5: Close stale issues

### #185

- [x] Comment that round-end capture now stores compact binary semantic history
  in `DrawingRecapEntry`.
- [x] Note that PNG encoding occurs only after an explicit user download.
- [x] Close as completed/no-longer-applicable with the current implementation
  evidence.
- [x] Do not open a download-specific follow-up without independent evidence
  that user-triggered PNG encoding is problematic.

### #150

- [x] Record that replay-canvas creation remains, but is limited to Undo and
  authoritative replay paths.
- [x] Record the persistent-memory tradeoff of caching an 800×600 canvas.
- [x] Attach the Phase 1 replay-allocation results.
- [x] Close as not planned because allocation/GC cost is immaterial in the
  current baseline.
- [x] Do not implement reuse; profiling did not contradict the closure decision.

## Phase 6: Update and close epic #191

- [x] Update the epic description with the completed work from #194, #197,
  #199, #207, and #208.
- [x] Mark the representative browser benchmark criterion complete.
- [x] Remove #185 and #150 from the active implementation order.
- [x] Replace the original #123 and #189 descriptions with links to their
  measurement-gated residual scopes.
- [x] Record the final #149 benchmark results.
- [x] Confirm that every remaining child issue is closed or moved to a clearly
  scoped follow-up.
- [x] Close #191 when no accepted performance budget is exceeded without a
  corresponding focused issue.

GitHub issue updates applied on 2026-08-15:

- #123 — rewritten, measured, and closed as completed;
- #149 — implemented in #256 and closed as completed;
- #189 — measured and closed as completed; replay remediation moved to #257;
- #257 — opened for bounded fill-heavy authoritative replay;
- #185 — closed as completed;
- #150 — closed as not planned;
- #191 — updated and closed after remaining work moved to #257.

## Verification commands

Run from the repository root unless noted otherwise:

```bash
(cd frontend && npm test)
(cd frontend && npm run lint)
(cd frontend && npm run build)
(cd backend && .venv/bin/pytest)
backend/.venv/bin/python benchmarks/canvas_history.py --near-limit
./benchmarks/run_canvas_history_browser.sh
./benchmarks/run_canvas.sh
./scripts/test-e2e.sh
```

Browser timings are diagnostic comparison data, not stable CI pass/fail
thresholds. Correctness, protocol bounds, and deterministic replay should be
covered by automated tests.

## Completion criteria

- [x] Flood fill preserves existing pixels and eight-connected semantics while
  materially reducing large-fill allocation or latency.
- [x] Interactive stroke readback is closed with evidence
  that it is not a material bottleneck.
- [ ] Worst-case synchronization and replay behaviour has documented budgets
  and automated bounds.
- [ ] Checkpointing is implemented only if measurements demonstrate that it is
  required.
- [x] Obsolete or uneconomic issues are closed with evidence and links.
- [x] Desktop, throttled-mobile, unit, integration, build, and cross-browser
  verification pass.
