# Performance Epic #191: Phase 2 Results

## Change

The per-pixel eight-neighbour flood-fill stack was replaced with an
eight-connected scanline/span algorithm. It retains a fixed one-byte status per
pixel (480 KB at 800×600), queues each pixel at most once, and stores one numeric
seed per adjacent horizontal run.

The implementation preserves:

- diagonal-only eight-connectivity;
- `FLOOD_FILL_CHANNEL_TOLERANCE` matching;
- no-op and bounds behaviour;
- deterministic, pixel-equivalent output relative to the previous algorithm.

## Verification

- 48 frontend unit tests passed.
- ESLint passed.
- TypeScript and the production Vite build passed.
- 21 multi-browser Playwright E2E tests passed.
- `git diff --check` passed.
- Desktop and throttled-mobile canvas benchmarks completed twice.

The tests include diagonal connectivity, no-op fills, tolerance, canvas
boundaries, narrow passages, isolated islands, alternating diagonal runs, a
large tolerance-close fill, and 40 deterministic differential fixtures against
the previous eight-neighbour implementation.

## Primary benchmark comparison

| Metric | Desktop before | Desktop after | Mobile 4× before | Mobile 4× after |
|---|---:|---:|---:|---:|
| Full fill, observer-visible | 75.9 ms | 16.2 ms | 266.9 ms | 54.1 ms |
| Full fill handler | 28.9 ms | 7.0 ms | 121.7 ms | 25.2 ms |
| Full fill heap delta | 89.9 MB | 2.5 MB | 90.2 MB | 2.5 MB |
| Full fill long task | none | none | 124 ms | none |
| Complex fill, observer-visible | 26.2 ms | 12.8 ms | 95.2 ms | 35.6 ms |
| Complex fill handler | 12.1 ms | 5.5 ms | 46.6 ms | 15.8 ms |
| Complex fill heap delta | 22.0 MB | 2.5 MB | 22.8 MB | 2.5 MB |
| Remote stroke p95 | 55.5 ms | 56.0 ms | 52.3 ms | 53.8 ms |
| Local stroke handler p95 | 1.4 ms | 1.7 ms | 5.4 ms | 6.2 ms |
| Undo/replay median | 24.1 ms | 24.0 ms | 30.8 ms | 32.0 ms |

The full-fill observer latency improved by approximately 79% on both profiles,
and transient heap growth fell by approximately 97%. The throttled-mobile long
task disappeared.

A confirmation run measured 16.9 ms desktop and 51.7 ms throttled-mobile full
fill latency. Its local stroke p95 values were 1.5 ms and 4.9 ms, while
Undo/replay medians were 24.0 ms and 31.7 ms. This confirms that the small
stroke/Undo differences in the primary run are normal run-to-run variation,
not a regression in paths that the fill change does not modify.

## Raw artifacts

- `docs/performance-191-phase2.json`
- `docs/performance-191-phase2-repeat.json`
- `docs/performance-191-phase2-traces/desktop.trace.json`
- `docs/performance-191-phase2-traces/desktop.heapprofile.json`
- `docs/performance-191-phase2-traces/mobile-throttled.trace.json`
- `docs/performance-191-phase2-traces/mobile-throttled.heapprofile.json`

These results are diagnostic comparisons from one machine, not portable timing
thresholds.
