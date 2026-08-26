import { useCallback, useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Chip } from "../components/ui/Chip";
import { SectionLabel } from "../components/ui/Card";
import { RoundsIcon } from "../components/icons";

import { ApiError } from "../lib/api";
import {
  abandonmentRate,
  readAuditLedger,
  readDailyTotals,
  readLiveMetrics,
  readPlayerActivity,
  readRuntimeEvents,
  seriesFor,
  type AuditEntry,
  type DailyTotal,
  type LiveMetrics,
  type RuntimeEventRow,
} from "../lib/operations";

const TRENDS = [
  { metric: "room.created", label: "Rooms opened" },
  { metric: "game.finished", label: "Games finished" },
  { metric: "game.abandoned", label: "Games abandoned" },
  { metric: "player.disconnected", label: "Disconnects" },
  { metric: "timer.overran", label: "Timer overruns" },
];

const CHART_DAYS = 14;
const LEDGER_PREVIEW = 6;

function shortTime(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  if (then.toDateString() === now.toDateString()) {
    return then.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  return then.toLocaleDateString([], { month: "short", day: "numeric" });
}

function axisLabel(date: string): string {
  return new Date(`${date}T00:00:00`).toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
}

/** The ledger names what happened; the chip names which system did it. */
function auditTag(eventType: string): { label: string; kind: "danger" | "success" | "primary" | "neutral" } {
  if (/ban|suspend|moderation|report/.test(eventType)) {
    return { label: "Moderation", kind: "danger" };
  }
  if (/retention|cleanup|rollup/.test(eventType)) {
    return { label: "Retention", kind: "success" };
  }
  if (/admin/.test(eventType)) return { label: "Admin", kind: "primary" };
  return { label: "Logged", kind: "neutral" };
}

function DailyBars({ days, metric }: { days: DailyTotal[]; metric: string }) {
  const series = seriesFor(days, metric).slice(-CHART_DAYS);
  const max = Math.max(1, ...series.map((point) => point.value));
  if (series.length === 0) {
    return <p className="ops-empty">Nothing recorded yet.</p>;
  }
  return (
    <>
      <div
        className="ops-chart-bars"
        role="img"
        aria-label={`${metric} per day, last ${series.length} days`}
      >
        {series.map((point) => (
          <span
            key={point.date}
            className="ops-chart-bar"
            style={{ height: `${Math.round((point.value / max) * 100)}%` }}
            title={`${point.date}: ${point.value}`}
          />
        ))}
      </div>
      <div className="ops-chart-axis">
        <span>{axisLabel(series[0].date)}</span>
        {series.length > 2 && (
          <span>{axisLabel(series[Math.floor(series.length / 2)].date)}</span>
        )}
        <span>{axisLabel(series[series.length - 1].date)}</span>
      </div>
    </>
  );
}

/** The operator's view of the server, laid out as the mockup's dashboard:
status banner, live metric cards, a daily trend chart beside recorder health,
and the audit ledger. Live counts come from the worker's own memory, which is
exact because one worker owns everything; the chart comes from permanent daily
aggregates, which outlive the raw rows behind them. */
export function AdminOperationsPage() {
  const [live, setLive] = useState<LiveMetrics | null>(null);
  const [days, setDays] = useState<DailyTotal[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<RuntimeEventRow[]>([]);
  const [chartMetric, setChartMetric] = useState(TRENDS[0].metric);
  const [ledgerExpanded, setLedgerExpanded] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [eventFilter, setEventFilter] = useState("");
  const [roomFilter, setRoomFilter] = useState("");
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [showIds, setShowIds] = useState(false);
  const [player, setPlayer] = useState<{
    displayName: string;
    events: RuntimeEventRow[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not load operator data.",
    );
  }, []);

  const refresh = useCallback(() => {
    void Promise.all([
      readLiveMetrics(),
      readDailyTotals(),
      readAuditLedger({ limit: 200 }),
    ])
      .then(([metrics, daily, ledger]) => {
        setLive(metrics);
        setDays(daily.days);
        setAudit(ledger.entries);
        setCheckedAt(Date.now());
        setError(null);
      })
      .catch(fail);
  }, [fail]);

  const loadEvents = useCallback(() => {
    void readRuntimeEvents({
      limit: 200,
      eventType: eventFilter || undefined,
      roomId: roomFilter || undefined,
    })
      .then((result) => {
        setEvents(result.events);
        setError(null);
      })
      .catch(fail);
  }, [eventFilter, roomFilter, fail]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(tick);
  }, []);

  function inspect(userId: string | null) {
    if (!userId) return;
    void readPlayerActivity(userId)
      .then((result) =>
        setPlayer({ displayName: result.player.displayName, events: result.events }),
      )
      .catch(fail);
  }

  const rate = live ? abandonmentRate(live.games) : null;
  const chartLabel =
    TRENDS.find((trend) => trend.metric === chartMetric)?.label ?? chartMetric;
  const chartToday = useMemo(
    () => seriesFor(days, chartMetric).at(-1)?.value ?? 0,
    [days, chartMetric],
  );
  const checkedAgo =
    checkedAt === null ? null : Math.max(0, Math.round((now - checkedAt) / 1000));
  const recorderHealthy = !live || live.recorder.dropped === 0;
  const visibleAudit = ledgerExpanded ? audit : audit.slice(0, LEDGER_PREVIEW);

  return (
    <main className="ops-page">
      <AppHeader backLabel="Back to lobby" />
      <header className="ops-header">
        <div>
          <SectionLabel>Administrators only</SectionLabel>
          <h1>Server operations</h1>
        </div>
        <button type="button" className="btn btn-secondary" onClick={refresh}>
          <RoundsIcon size={15} />
          Refresh
        </button>
      </header>

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}

      {live && (
        <>
          <div
            className={`ops-status-banner${recorderHealthy ? "" : " is-warning"}`}
            role="status"
          >
            <span className="ops-status-dot" aria-hidden="true" />
            <strong>
              {recorderHealthy
                ? "All systems operational"
                : "Recorder dropped observations"}
            </strong>
            <span>
              Single worker · accepting rooms
              {checkedAgo !== null && ` · checked ${checkedAgo}s ago`}
            </span>
          </div>

          <section className="ops-metrics" aria-label="Live counts">
            <div className="ops-metric">
              <span className="ops-metric-label">Players online</span>
              <span className="ops-metric-value">{live.live.players}</span>
              <span className="ops-metric-note">
                peak {live.peak.players} · resets on restart
              </span>
            </div>
            <div className="ops-metric">
              <span className="ops-metric-label">Live rooms</span>
              <span className="ops-metric-value">{live.live.rooms}</span>
              <span className="ops-metric-note">peak {live.peak.rooms}</span>
            </div>
            <div className="ops-metric">
              <span className="ops-metric-label">Games running</span>
              <span className="ops-metric-value">{live.live.activeGames}</span>
              <span className="ops-metric-note">peak {live.peak.activeGames}</span>
            </div>
            <div
              className={`ops-metric${rate !== null && rate >= 25 ? " is-warning" : ""}`}
            >
              <span className="ops-metric-label">Abandoned</span>
              <span className="ops-metric-value">
                {rate === null ? "—" : `${rate}%`}
              </span>
              <span className="ops-metric-note">
                {live.games.abandoned} of{" "}
                {live.games.finished + live.games.abandoned + live.games.shutdown}
              </span>
            </div>
          </section>

          <div className="ops-columns">
            <section className="ops-card" aria-label="Daily trend">
              <div className="ops-card-head">
                <div>
                  <h2>{chartLabel}</h2>
                  <p className="ops-card-sub">
                    Last {CHART_DAYS} days · {chartToday} today
                  </p>
                </div>
                <select
                  className="ops-select"
                  aria-label="Charted metric"
                  value={chartMetric}
                  onChange={(change) => setChartMetric(change.target.value)}
                >
                  {TRENDS.map((trend) => (
                    <option key={trend.metric} value={trend.metric}>
                      {trend.label}
                    </option>
                  ))}
                </select>
              </div>
              <DailyBars days={days} metric={chartMetric} />
            </section>

            <section className="ops-card" aria-label="Recorder health">
              <div className="ops-card-head">
                <h2>Recorder health</h2>
                <Chip kind={recorderHealthy ? "success" : "warm"}>
                  {recorderHealthy ? "Healthy" : "Attention"}
                </Chip>
              </div>
              <div className="ops-health-row">
                <span className="ops-health-dot" aria-hidden="true" />
                <strong>Observations stored</strong>
                <span>{live.recorder.storedEvents.toLocaleString()}</span>
              </div>
              <div className="ops-health-row">
                <span className="ops-health-dot" aria-hidden="true" />
                <strong>Waiting to write</strong>
                <span>{live.recorder.buffered}</span>
              </div>
              <div
                className={`ops-health-row${recorderHealthy ? "" : " is-warning"}`}
              >
                <span className="ops-health-dot" aria-hidden="true" />
                <strong>Dropped this window</strong>
                <span>{live.recorder.dropped}</span>
              </div>
              <div className="ops-attention">
                <h3>Attention</h3>
                <p>
                  {!recorderHealthy
                    ? `${live.recorder.dropped} observations were dropped by a full buffer.`
                    : rate !== null && rate >= 25
                      ? `Abandoned games sit at ${rate}% this window. Nothing else needs an operator.`
                      : "Nothing needs an operator."}
                </p>
              </div>
            </section>
          </div>

          <section className="ops-card ops-ledger" aria-label="Audit ledger">
            <div className="ops-card-head">
              <div>
                <h2>Audit ledger</h2>
                <p className="ops-card-sub">
                  Recent operator and automated actions · append-only
                </p>
              </div>
              {audit.length > LEDGER_PREVIEW && (
                <button
                  type="button"
                  className="btn btn-ghost btn-compact"
                  onClick={() => setLedgerExpanded((current) => !current)}
                >
                  {ledgerExpanded ? "Show recent" : "View all"}
                </button>
              )}
            </div>
            {ledgerExpanded && (
              <div className="ops-filters">
                <label className="ops-toggle">
                  <input
                    type="checkbox"
                    checked={showIds}
                    onChange={(change) => setShowIds(change.target.checked)}
                  />
                  Show ids instead of names
                </label>
              </div>
            )}
            {visibleAudit.length === 0 && (
              <p className="ops-empty">Nothing recorded yet.</p>
            )}
            {visibleAudit.map((entry) => {
              const tag = auditTag(entry.eventType);
              const actor = showIds
                ? (entry.actorUserId ?? "system")
                : (entry.actorName ??
                  (entry.actorUserId ? "Deleted player" : "system"));
              const target = showIds
                ? (entry.targetId ?? "")
                : (entry.targetName ?? entry.targetId ?? "");
              return (
                <div key={entry.id} className="ops-audit-row">
                  <time dateTime={entry.createdAt}>{shortTime(entry.createdAt)}</time>
                  <span className="ops-audit-body">
                    <strong className={showIds ? "ops-identifier" : undefined}>
                      {actor}
                    </strong>{" "}
                    · {entry.eventType}
                    {entry.targetType && target && (
                      <>
                        {" · "}
                        <span className="ops-subject-kind">
                          {entry.targetType.replace(/_/g, " ")}
                        </span>{" "}
                        <span className={showIds ? "ops-identifier" : undefined}>
                          {target}
                        </span>
                      </>
                    )}
                  </span>
                  <Chip kind={tag.kind}>{tag.label}</Chip>
                </div>
              );
            })}
          </section>

          <details
            className="ops-card ops-activity"
            open={activityOpen}
            onToggle={(toggle) => {
              const open = (toggle.target as HTMLDetailsElement).open;
              setActivityOpen(open);
              if (open && events.length === 0) loadEvents();
            }}
          >
            <summary>Recorded activity</summary>
            <div className="ops-filters">
              <label htmlFor="ops-event-type">Event</label>
              <input
                id="ops-event-type"
                value={eventFilter}
                onChange={(change) => setEventFilter(change.target.value)}
                placeholder="player.disconnected"
              />
              <label htmlFor="ops-room">Room</label>
              <input
                id="ops-room"
                value={roomFilter}
                onChange={(change) => setRoomFilter(change.target.value)}
                placeholder="room id"
              />
              <button
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={loadEvents}
              >
                Apply
              </button>
            </div>
            <div className="ops-table-scroll">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Event</th>
                    <th scope="col">Room</th>
                    <th scope="col">Value</th>
                    <th scope="col">Player</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((row) => (
                    <tr key={row.id}>
                      <td>{new Date(row.occurredAt).toLocaleString()}</td>
                      <td>{row.eventType}</td>
                      <td>{row.roomId ?? "—"}</td>
                      <td className="ops-number">{row.value ?? "—"}</td>
                      <td>
                        {row.userId ? (
                          <button
                            type="button"
                            className="auth-link"
                            onClick={() => inspect(row.userId)}
                          >
                            Inspect
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {events.length === 0 && (
              <p className="ops-empty">Nothing recorded yet.</p>
            )}
          </details>
        </>
      )}

      {player && (
        <div
          className="modal-overlay"
          onMouseDown={(click) => {
            if (click.target === click.currentTarget) setPlayer(null);
          }}
        >
          <div
            className="modal-card ops-player-dialog"
            role="dialog"
            aria-modal="true"
          >
            <h3 className="modal-title">{player.displayName}</h3>
            <p className="modal-body">
              Opening this view is itself recorded in the audit ledger.
            </p>
            <div className="ops-table-scroll">
              <table className="ops-table">
                <tbody>
                  {player.events.map((row) => (
                    <tr key={row.id}>
                      <td>{new Date(row.occurredAt).toLocaleString()}</td>
                      <td>{row.eventType}</td>
                      <td>{row.roomId ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              type="button"
              className="modal-dismiss"
              onClick={() => setPlayer(null)}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
