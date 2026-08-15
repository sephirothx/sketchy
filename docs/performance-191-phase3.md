# Performance Epic #191: Phase 3 Results

## Decision

Close #123 without changing the renderer. Representative local drawing stays
within the frame budget on both measured profiles, and synchronous canvas
readback/upload is a small fraction of the interaction handler. The evidence
does not justify adding frame coalescing, a retained CPU pixel surface,
`OffscreenCanvas`, or a worker.

## Measurements

The Phase 1 benchmark recorded 12 representative strokes per profile with
Playwright Chromium 149. The mobile profile used a 390×844 viewport and 4× CPU
throttling.

| Metric | Desktop | Mobile, 4× CPU |
|---|---:|---:|
| Local handler median | 1.10 ms | 3.35 ms |
| Local handler p95 | 1.40 ms | 5.40 ms |
| `getImageData` median | <0.05 ms | 0.15 ms |
| `getImageData` calls, median | 6 | 6 |
| `putImageData` median | <0.05 ms | 0.05 ms |
| `putImageData` calls, median | 6 | 6 |
| Combined readback/upload median | 0.05 ms | 0.30 ms |
| Non-I/O handler time, upper bound | 1.05 ms | 3.05 ms |
| Heap delta per stroke, median | 85.7 KiB | 122.3 KiB |

The non-I/O value subtracts measured canvas readback/upload from total handler
time. It is an upper bound for pixel processing because it also contains input
dispatch and other JavaScript work.

The complete DevTools traces contain garbage collection across the full mixed
fill, stroke, synchronization, and Undo workload. Some minor collections overlap
pointer dispatch, but the observed handler p95 already includes those pauses and
remains 5.4 ms under 4× throttling. No local drawing long task or visible ink
stall was observed.

Drawer-to-observer latency remains approximately 50 ms because the transport
deliberately batches updates for 40 ms. It is not evidence of synchronous local
rasterization cost.

## Disposition

- #147 already removed React state updates from pointer movement.
- #148 already batched multi-segment observer rasterization.
- The remaining bounded-region `getImageData`/`putImageData` path is not a
  demonstrated bottleneck.
- #123 is therefore complete as a profiling investigation and should be closed
  with no renderer change.

These timings are diagnostic results from one machine, not portable CI
thresholds.
