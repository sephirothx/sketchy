# Performance Epic #191: Preliminary Baseline

## Run metadata

- Date: 2026-08-15
- Commit: `0ccc99601da701ee391a3c727c393fe6dc83785d`
- Platform: macOS/Darwin 25.5.0, arm64 (`T6041`)
- Browser: Playwright Chromium 149.0.7827.55, headless
- Profiles: desktop at 1× CPU and 390×844 mobile at 4× CPU throttling
- Workload: 12 measured strokes, 60 replay-history strokes, and 5 measured
  Undo operations
- Command:

  ```bash
  PORT=18772 ./benchmarks/run_canvas.sh \
    --json-output docs/performance-191-baseline.json \
    --trace-dir docs/performance-191-traces
  ```

Raw artifacts:

- `docs/performance-191-baseline.json`
- `docs/performance-191-traces/desktop.trace.json`
- `docs/performance-191-traces/desktop.heapprofile.json`
- `docs/performance-191-traces/mobile-throttled.trace.json`
- `docs/performance-191-traces/mobile-throttled.heapprofile.json`

The timeline traces include the full-canvas fill, nested-boundary fill, fast
strokes, full-history synchronization, and five consecutive Undo/replay
operations. Heap deltas in the JSON are measured around each interaction; the
heap profiles provide allocation samples across the complete profile.

## Summary

| Metric | Desktop | Mobile, 4× CPU |
|---|---:|---:|
| Remote stroke p50 | 49.6 ms | 50.1 ms |
| Remote stroke p95 | 55.5 ms | 52.3 ms |
| Local stroke handler p50 | 1.1 ms | 3.4 ms |
| Local stroke handler p95 | 1.4 ms | 5.4 ms |
| Local stroke readback median | <0.1 ms | 0.2 ms |
| Full-canvas fill, observer-visible | 75.9 ms | 266.9 ms |
| Full-canvas fill handler | 28.9 ms | 121.7 ms |
| Full-canvas fill heap delta | 89.9 MB | 90.2 MB |
| Full-canvas fill long task | none | 124 ms |
| Nested-boundary fill, observer-visible | 26.2 ms | 95.2 ms |
| Nested-boundary fill handler | 12.1 ms | 46.6 ms |
| Nested-boundary fill heap delta | 22.0 MB | 22.8 MB |
| Undo/replay p50, 5 samples | 24.1 ms | 30.8 ms |
| Undo/replay p95, 5 samples | 24.5 ms | 33.2 ms |
| Local Undo interaction | 16.6 ms | 27.9 ms |
| Local Undo readback calls, median | 276 | 276 |
| Replay canvas creations per Undo | 2 | 2 |
| `sync_strokes`, 72 synchronized actions | 1,736 B | 1,736 B |

## Preliminary interpretation

- **#149 is confirmed as the first implementation target.** The current
  full-canvas fill creates an approximately 90 MB transient heap increase. On
  the throttled-mobile profile it blocks the interaction handler for 121.7 ms
  and produces a 124 ms long task. Readback/upload accounts for only 3.2 ms;
  pixel traversal and the dynamically growing neighbour stack dominate.
- **#123 should remain measurement-gated and lower priority.** Representative
  local stroke handling is approximately 5.4 ms at p95 on the throttled
  profile, while measured canvas readback/upload time is approximately 0.2 ms
  per stroke.
  The roughly 50 ms remote latency is consistent with the deliberate 40 ms
  transport batching interval and is not evidence of a local rendering stall.
- **#150 remains unsupported by the baseline.** Undo/replay stays below 36 ms
  at p95 on the throttled profile. Each Undo currently creates two scratch
  canvases, but their measured creation time rounds below the clock resolution,
  retained heap growth is under 0.5 MB, and replay rasterization remains the
  larger operation.
- **#189 still requires a separate near-limit workload.** The representative
  72-action synchronized history is only 1,736 bytes. This baseline verifies
  the normal path but does not answer worst-case reconnect or replay behaviour.

These measurements are comparison data from one machine, not portable pass/fail
thresholds.
