# Performance Epic #191: Phase 4 Results

## Decision

Close broad measurement issue #189 and move the one failed dimension to focused
follow-up #257. Payload size, packed server state, binary encoding/decoding, and
path/shape replay are within budget. Fill-heavy and mixed authoritative replay
are not safely bounded by the current 20,000-action limit.

Checkpointing is now eligible because replay is a demonstrated bottleneck. It
is not predetermined: #257 must compare a weighted replay-work limit, raster
checkpoints with semantic deltas, and a threshold-based hybrid.

## Accepted budgets

| Dimension | Budget |
|---|---:|
| Maximum binary `sync_strokes` history | 512 KiB |
| Complete retained canvas session per room | 2 MiB |
| Backend binary encode or decode | 25 ms |
| Browser binary decode, desktop | 50 ms |
| Browser binary decode, mobile at 4× CPU | 200 ms |
| Complete authoritative replay, desktop | 1 second |
| Complete authoritative replay, mobile at 4× CPU | 3 seconds |

Browser timings are reference-machine diagnostic budgets, not CI timing
assertions. Structural payload and state bounds are enforced automatically.

## Server and payload measurements

All fixtures use 20,000 actions. Path-heavy, mixed, and theoretical-maximum
fixtures also use the complete 25,000-point allowance.

| Fixture | Points | Binary | Packed history | Complete session | Encode | Decode |
|---|---:|---:|---:|---:|---:|---:|
| Path-heavy | 25,000 | 280,011 B | 287,273 B | 1,152,364 B | 0.80 ms | 5.11 ms |
| Shape-heavy | 0 | 360,011 B | 396,284 B | 1,261,375 B | 0.84 ms | 5.42 ms |
| Fill-heavy | 0 | 240,011 B | 262,513 B | 1,127,604 B | 0.84 ms | 4.17 ms |
| Mixed | 25,000 | 358,761 B | 375,865 B | 1,240,956 B | 0.85 ms | 4.93 ms |
| Theoretical maximum | 25,000 | 460,002 B | 495,591 B | 1,360,682 B | 0.85 ms | 5.36 ms |

The exact 460,002-byte maximum is derived from the binary layout and verified
by an automated test that constructs and round-trips the maximizing history.

## Browser late-join and reconnect measurements

Playwright Chromium 149 measured the production decoder and renderer. “Late
join” is a cold authoritative decode/replay in a newly loaded benchmark page;
“reconnect” repeats the authoritative decode/replay on the existing page. The
binary byte count separately bounds transfer size.

| Profile | Fixture | Replayed | Decode | Late join replay | Reconnect replay |
|---|---|---:|---:|---:|---:|
| Desktop | Path-heavy | 20,000 / 20,000 | 8.7 ms | 45.0 ms | 31.8 ms |
| Desktop | Shape-heavy | 20,000 / 20,000 | 2.6 ms | 390.9 ms | 376.6 ms |
| Desktop | Fill-heavy | 100 / 20,000 | 1.8 ms | 650.0 ms | 636.5 ms |
| Desktop | Mixed | 400 / 20,000 | 3.5 ms | 495.5 ms | 490.3 ms |
| Mobile, 4× | Path-heavy | 20,000 / 20,000 | 11.5 ms | 152.0 ms | 119.9 ms |
| Mobile, 4× | Shape-heavy | 20,000 / 20,000 | 9.3 ms | 1,563.0 ms | 1,536.8 ms |
| Mobile, 4× | Fill-heavy | 100 / 20,000 | 5.7 ms | 2,591.3 ms | 2,611.5 ms |
| Mobile, 4× | Mixed | 400 / 20,000 | 10.5 ms | 2,039.2 ms | 2,078.9 ms |

Full path- and shape-heavy histories pass the replay budgets. Fill-heavy and
mixed histories are time-bounded samples: replaying the accepted 20,000-fill
fixture synchronously would occupy the main thread for minutes. Linear
diagnostic projections are approximately 130 seconds desktop and 522 seconds
throttled mobile for fill-heavy replay, and 25 seconds / 104 seconds for mixed
replay. The projections are not acceptance measurements; the observed 100-fill
sample already demonstrates that the current action limit does not safely bound
mobile replay.

## Bounds and graceful recovery changes

- `MAX_BINARY_CANVAS_HISTORY_BYTES` documents the exact 460,002-byte wire bound.
- The server refuses Clear when history already contains 20,000 actions.
- The client already retains at most 256 pending mutations.
- The server now retains the latest 512 commits instead of an unbounded list.
- A duplicate older than the retained commit window receives an authoritative
  sync, preserving recovery without retaining every acknowledgement forever.
- Existing 20,000-action and 25,000-point decoder/session limits remain intact.

## Verification

- 219 backend tests passed.
- 48 frontend unit tests passed.
- Frontend lint and production build passed.
- 21 Chromium/Firefox end-to-end tests passed.
- The server near-limit benchmark completed.
- Desktop and throttled-mobile browser history benchmarks completed.
- Shell syntax and `git diff --check` passed.

Raw local artifacts:

- `docs/performance-191-phase4-server.json`
- `docs/performance-191-phase4-browser-desktop.json`
- `docs/performance-191-phase4-browser-mobile.json`
