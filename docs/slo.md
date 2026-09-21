# Service level objectives

What "healthy" means for one Sketchy worker, stated in the series `/metrics` exposes so
that an alert, a dashboard and a person at the console all read the same number. The
thresholds here are the ones in [`ops/prometheus/rules/sketchy-alerts.yml`](../ops/prometheus/rules/sketchy-alerts.yml)
and [`sketchy-postgres.yml`](../ops/prometheus/rules/sketchy-postgres.yml);
change one and change the other in the same commit. The recording rules in
[`sketchy-recording.yml`](../ops/prometheus/rules/sketchy-recording.yml) compute the ratios
and percentiles once, and [`backend/tests/test_alert_rules.py`](../backend/tests/test_alert_rules.py)
refuses a rule that names a series the server does not expose, or a postgres_exporter
series whose collector the scrape example leaves off.

The single-worker topology is a published decision (`docs/requirements.md` §13, N-01),
so these objectives are per process and there is no fleet to average over. A restart
resets every in-memory series; Prometheus keeps the history.

## Objectives

| # | Objective | Measured by | Window | Alert |
| --- | --- | --- | --- | --- |
| **SLO-1** | A game can be played: guest, create, join, start, draw, leave all succeed within 20 s - and the probe itself keeps running | `sketchy_probe_success` and `sketchy_probe_last_run_timestamp_seconds` from `python -m app.probe` (textfile collector) | ≥ 99.5 % of probe runs over 30 days | `SketchyProbeFailing` (page, 5 m); `SketchyProbeStale` (page, 5 m) when the last run is over five minutes old or the series is absent |
| **SLO-2** | The process is up and can reach its database | `up{job="sketchy"}`, `sketchy_db_ready` (refreshed by the scrape, so it needs no `/api/ready` caller) | ≥ 99.9 % over 30 days | `SketchyDown`, `SketchyDatabaseUnreachable` (page, 2 m) |
| **SLO-3** | API requests succeed | `sketchy:http_error_ratio:5m` | < 1 % 5xx over any 5 m | `SketchyHighErrorRate` (page) |
| **SLO-4** | Client commands do not raise | `sketchy:socket_error_ratio:5m` | < 0.5 % `outcome="error"` over any 5 m | `SketchySocketErrors` (page) |
| **SLO-5** | The event loop keeps time | `sketchy:loop_lag_p95_seconds:5m` | p95 < 250 ms | `SketchyLoopLag` (page, 5 m) |
| **SLO-6** | API requests are fast | `sketchy:http_p95_seconds:5m` | p95 < 300 ms | `SketchySlowRequests` (warn, 10 m) |
| **SLO-7** | Command handlers are fast | `sketchy:socket_p95_seconds:5m` | p95 < 100 ms | `SketchySlowCommands` (warn, 10 m) |
| **SLO-8** | Nothing a player did is lost | `sketchy_history_writes_abandoned_total`, `sketchy_events_dropped_total` | zero | `SketchyHistoryWritesLost` (page), `SketchyRecorderDropping` (warn) |
| **SLO-9** | Deferred work is carried out | `sketchy_mail_outbox_oldest_seconds`, `sketchy_data_exports_oldest_seconds`, `sketchy_finished_games_oldest_seconds`, `sketchy_loop_*` | oldest < 10 min (a staged finished game < 1 h, its retry schedule); every loop running and not failing | `SketchyMailBacklog`, `SketchyExportStuck`, `SketchyFinishedGamesStuck`, `SketchyLoopFailing` (warn), `SketchyLoopStopped` (page) |
| **SLO-10** | Data is deleted when policy says it is | `sketchy_retention_overdue_seconds` against `sketchy_retention_sla_seconds`, per table | every table inside its own deletion SLA — six hours past eligibility, a day for guests and retired lists ([`database.md`](database.md) §10) | `SketchyRetentionBehind` (warn, 30 m); `SketchyRetentionSweepFailing` (warn, 2 h) and `SketchyRetentionSweepStarved` (warn, 6 h) name the table |

SLO-10 is the one objective that is a promise to somebody outside the deployment rather
than to a player at the keyboard, which is why it is measured rather than assumed. A
retention loop that runs every hour and never fails is not evidence that anything was
deleted on time: it is evidence that something ran. What is measured instead is what
each sweep *left* — the age of the oldest row it should already have removed, over the
sweep's own eligibility predicate so that rows a policy exempts (a suspended account's
sessions, a pinned prompt revision, protected report evidence) are never counted as
lateness. Because a clean table reports a zero rather than nothing, "no series" is a
broken exporter and not a compliant table.

Saturation signals - pool fill, statement p95, disk, memory - are not objectives but
warnings, because each one is a cause the objectives above would show the effect of:
`SketchyPoolSaturated`, `SketchySlowQueries`, `SketchyDiskLow` (page: a full disk is
data loss), `SketchyMemoryHigh`.

The connection has four of those warnings (#881), each a network or proxy problem a
player feels as lag or a stuck canvas before any objective moves:
`SketchyPollingShareHigh` (over a fifth of open sockets on long-polling for 30 m — an
upgrade the network is not passing), `SketchyCompressionMissing` (over a tenth of new
WebSockets without permessage-deflate in 30 m — a proxy stripping the extension, at ~8×
the bytes), `SketchyBacklogClosures` (any socket closed for its outbound backlog), and
`SketchyCanvasRecoveries` (non-deferred canvas recovery notices above one per two open
sockets per 15 m). Each has a floor on the population so a quiet night with a handful of
sockets does not fire it. The series that explain them — disconnects by reason, session
length, seat rebind time against the 30 s grace, Engine.IO ping round trip, polling
upgrades, stale clients — are listed in wire §9; they have no alert of their own until
beta traffic says what normal looks like.

The database's application-side signals name a cause as well as an effect (#892).
`sketchy_db_query_duration_seconds` is labelled by `operation` (session resolve, save
game, prompt usage, message batch, event flush, gallery page, community catalogue,
history page, export build, retention sweep, profile pins, stats rebuild, other) and
reaches 30 s, the web role's statement timeout, so a slow p95 has a name.
`sketchy_db_pool_wait_seconds` is the wait for a connection, which that histogram
starts after: `SketchyPoolWaiting` (warn, p95 over 100 ms for 5 m) is the queue the
fill ratio only implies, and `SketchyPoolTimeouts` (page) is a request that gave up
waiting — a failure the statement counters never saw, because no cursor existed.
`sketchy_db_query_errors_total{cause}` splits failures by SQLSTATE class, and
`SketchyDatabaseDeadlocks` (warn) fires on any deadlock or serialization failure in an
hour: the ascending lock order and the 5 s lock budget exist so that it never does.
`sketchy_db_transaction_seconds{operation}` is how long each kind of transaction holds
its connection, which is what a pool sized 5 + 5 has to be judged against;
`sketchy_db_retries_total{operation,outcome}` counts the retried writes; and
`sketchy_history_write_seconds` and `sketchy_history_persist_lag_seconds` say how long
a finished game takes to write and how long after the game it lands.

On PostgreSQL the disk is the database host's: the application does not emit
`sketchy_data_disk_*` there (its working directory is not where the data is), and
`sketchy:disk_free_ratio` reads node_exporter on the database host instead, so
`SketchyDiskLow` watches the right volume on either engine. node_exporter reports every
mount on that host; the scrape labels the data directory's mount `volume="database"`
([`scrape-example.yml`](../ops/prometheus/scrape-example.yml)) and the disk rules read
only that series, so a full root or backup disk does not page as a full database.

The database's own view of itself comes from postgres_exporter
([`sketchy-postgres.yml`](../ops/prometheus/rules/sketchy-postgres.yml), #889). None of
these is an objective either; each is a cause that shows up later as a slow statement
or a full disk, caught while it is still a trend. All warn:

| Alert | Fires when | What it usually is |
| --- | --- | --- |
| `SketchyPostgresExporterDown` | the exporter is not scraped, or cannot reach the database, for 5 m | every rule below is silent with it |
| `SketchyPostgresDeadTuples` | a churn table is over 20 % dead tuples (and over 10,000) for 2 h | autovacuum not keeping up with a sweep, or a long transaction holding the horizon |
| `SketchyPostgresAutovacuumStale` | a churn table with over 10,000 dead tuples has not been autovacuumed for 3 days | the same, seen from the vacuum side |
| `SketchyPostgresCacheMisses` | under 95 % of block reads hit shared buffers for 6 h | the working set outgrew `shared_buffers`, or a statement scans a large table |
| `SketchyPostgresLongTransaction` | a transaction has been open 15 minutes | an operator session: no application budget allows one |
| `SketchyPostgresConnectionsHigh` | over 80 % of `max_connections` in use for 10 m | operator sessions on top of the web pool |
| `SketchyPostgresWraparound` | `age(datfrozenxid)` over 500 million for 1 h | anti-wraparound vacuums not finishing |
| `SketchyPostgresCheckpointsRequested` | more checkpoints forced by WAL volume than by time in a day | `max_wal_size` too small for the write rate |
| `SketchyDatabaseGrowthDoubled` | the database grew over twice last week's growth (and over 1 GB) | a new writer or a stopped sweep |
| `SketchyDatabaseVolumeFillsSoon` | the last week's trend fills the database volume within 30 days | growth, ahead of `SketchyDiskLow` |

The integrity audit (#894, [`database.md`](database.md) §13) is the detection bound
for silent damage: `SketchyDrawingCorrupt` (page) is a stored drawing that no longer
reads back, found within one audit cycle; `SketchyIntegrityDrift` (warn) is a projection
or writer invariant that disagrees with its facts; `SketchyIntegrityCycleOverdue` (warn)
is a check that has not finished a pass over its table in twice its target, which
would leave the bound unkept.

`SketchyDrawingStoreLarge` is neither, and is the only alert here that asks for a
decision rather than a fix. `sketchy_drawing_store_bytes` is what the stored drawings
occupy; #471 measured them, chose to keep the bytes in the primary database, and named
50 GB as the size at which that choice is reopened, because past there the blobs
dominate what a backup and a restore have to move (see *Storing the drawings* in
[`database.md`](database.md)). The store only ever grows, so the alert cannot be
transient and there is nothing to do at 3 a.m.: it fires once, warns, and stays until
somebody costs the alternatives again.

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
  survive the server being down - which is when they matter. The other side of that:
  a textfile says whatever the last run wrote until something overwrites it, so
  `SketchyProbeStale` pages on `sketchy_probe_last_run_timestamp_seconds` falling more
  than five minutes behind, or on the series being absent - a dead cron, a wrong
  textfile path, or a textfile job nobody scraped all look the same as an outage,
  because for the purpose of knowing whether a game can be played they are one. The
  scrape example carries the node_exporter job for this reason.
- Counters reset on restart; `rate()` and `increase()` handle that, plain comparisons
  do not.
- The dashboards ([`ops/grafana/`](../ops/grafana/), #968) read the same recording
  rules the alerts do, so a panel and the alert beside it cannot disagree about what a
  p95 is. A trend older than Prometheus's retention is gone: the default is 15 days, and
  since #965 no daily roll-up in the database keeps one, so run Prometheus with
  `--storage.tsdb.retention.time=1y` or longer.

## Where the probe runs

Anywhere with Python that can reach the service - a cron entry on the host, a
node_exporter textfile job, or a separate monitor:

```bash
*/1 * * * * cd /srv/sketchy/backend && .venv/bin/python -m app.probe \
    --base-url https://sketchy.example \
    --textfile /var/lib/node_exporter/textfile/sketchy.prom
```

It keeps its two guest sessions between runs in `--state` (default
`~/.cache/sketchy/probe-sessions.json`), checking each with one request before use and
provisioning a replacement only when the server no longer knows it. That is what makes
a one-minute cadence safe: guest provisioning is rate-limited per client
(`GUEST_PROVISION_LIMIT`, 60 an hour by default), and a probe minting two guests a
minute would page on its own rate limit after half an hour. The accounts are named
`probeh…` and `probeg…`; if the state file is lost they are provisioned again and the
old ones go the way of any idle guest. `--no-state` disables the reuse, for a one-off
run from a laptop.
