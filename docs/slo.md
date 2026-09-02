# Service level objectives

What "healthy" means for one Sketchy worker, stated in the series `/metrics` exposes so
that an alert, a dashboard and a person at the console all read the same number. The
thresholds here are the ones in [`ops/prometheus/rules/sketchy-alerts.yml`](../ops/prometheus/rules/sketchy-alerts.yml);
change one and change the other in the same commit. The recording rules in
[`sketchy-recording.yml`](../ops/prometheus/rules/sketchy-recording.yml) compute the ratios
and percentiles once, and [`backend/tests/test_alert_rules.py`](../backend/tests/test_alert_rules.py)
refuses a rule that names a series the server does not expose.

The single-worker topology is a published decision (`docs/requirements.md` §13, N-01),
so these objectives are per process and there is no fleet to average over. A restart
resets every in-memory series; Prometheus keeps the history.

## Objectives

| # | Objective | Measured by | Window | Alert |
| --- | --- | --- | --- | --- |
| **SLO-1** | A game can be played: guest, create, join, start, draw, leave all succeed within 20 s | `sketchy_probe_success` from `python -m app.probe` (textfile collector) | ≥ 99.5 % of probe runs over 30 days | `SketchyProbeFailing` (page, 5 m) |
| **SLO-2** | The process is up and can reach its database | `up{job="sketchy"}`, `sketchy_db_ready` | ≥ 99.9 % over 30 days | `SketchyDown`, `SketchyDatabaseUnreachable` (page, 2 m) |
| **SLO-3** | API requests succeed | `sketchy:http_error_ratio:5m` | < 1 % 5xx over any 5 m | `SketchyHighErrorRate` (page) |
| **SLO-4** | Client commands do not raise | `sketchy:socket_error_ratio:5m` | < 0.5 % `outcome="error"` over any 5 m | `SketchySocketErrors` (page) |
| **SLO-5** | The event loop keeps time | `sketchy:loop_lag_p95_seconds:5m` | p95 < 250 ms | `SketchyLoopLag` (page, 5 m) |
| **SLO-6** | API requests are fast | `sketchy:http_p95_seconds:5m` | p95 < 300 ms | `SketchySlowRequests` (warn, 10 m) |
| **SLO-7** | Command handlers are fast | `sketchy:socket_p95_seconds:5m` | p95 < 100 ms | `SketchySlowCommands` (warn, 10 m) |
| **SLO-8** | Nothing a player did is lost | `sketchy_history_writes_abandoned_total`, `sketchy_events_dropped_total` | zero | `SketchyHistoryWritesLost` (page), `SketchyRecorderDropping` (warn) |
| **SLO-9** | Deferred work is carried out | `sketchy_mail_outbox_oldest_seconds`, `sketchy_data_exports_oldest_seconds`, `sketchy_loop_*` | oldest < 10 min; every loop running and not failing | `SketchyMailBacklog`, `SketchyExportStuck`, `SketchyLoopFailing` (warn), `SketchyLoopStopped` (page) |

Saturation signals - pool fill, statement p95, disk, memory - are not objectives but
warnings, because each one is a cause the objectives above would show the effect of:
`SketchyPoolSaturated`, `SketchySlowQueries`, `SketchyDiskLow` (page: a full disk is
data loss), `SketchyMemoryHigh`.

## Error budgets

| Objective | Budget over 30 days | What spends it |
| --- | --- | --- |
| SLO-1 (99.5 %) | 3 h 36 min of failing probes | a deploy that breaks a handler, a full room ceiling, a stalled loop |
| SLO-2 (99.9 %) | 43 min down or database-less | restarts beyond the drain, database maintenance, a host reboot |
| SLO-3 / SLO-4 | 1 % / 0.5 % of requests or commands, per window | an unhandled exception in one endpoint or command |
| SLO-5 | any 5 m window with p95 ≥ 250 ms | a synchronous write, a large JSON dump, a garbage-collection pause, a busy host |

The budgets are deliberately generous for v1: the deploy model is a drain and a
restart with no failover (N-01, R-SHUT-06), and each planned restart costs SLO-2 up to
the drain bound. A budget that is spent before the month ends is the signal to stop
shipping features and look at what spent it.

## How to read the numbers

- Every rate and ratio is over a **5-minute** window because that is what the
  operations overview shows (`windowMinutes`), so the page and the rule agree.
- Percentiles are `histogram_quantile` estimates over fixed buckets
  (`backend/app/services/telemetry.py`), so a p95 reads as "at most the bucket bound
  it fell in". The buckets are dense where the thresholds sit.
- `sketchy_probe_*` come from the probe's textfile, not from the server, so they
  survive the server being down - which is when they matter.
- Counters reset on restart; `rate()` and `increase()` handle that, plain comparisons
  do not.

## Where the probe runs

Anywhere with Python that can reach the service - a cron entry on the host, a
node_exporter textfile job, or a separate monitor:

```bash
*/1 * * * * cd /srv/sketchy/backend && .venv/bin/python -m app.probe \
    --base-url https://sketchy.example \
    --textfile /var/lib/node_exporter/textfile/sketchy.prom
```

It creates two guest accounts per run, named `probeh…` and `probeg…`, which
the guest retention sweep removes like any other idle guest.
