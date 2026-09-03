import { useClock } from "../hooks/useClock";
import { formatClock, type TimeFormat } from "../lib/clock";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { NotFoundPage } from "./NotFoundPage";
import { Chip } from "../components/ui/Chip";
import { SectionLabel } from "../components/ui/Card";
import { RoundsIcon } from "../components/icons";

import { ApiError } from "../lib/api";
import {
  admissionLabel,
  isAdmitting,
  mergeAdmission,
  readMaintenance,
  type MaintenanceState,
} from "../lib/adminControls";
import { useAdmissionNotices } from "../hooks/useAdmissionNotices";
import { canAdminister } from "../lib/operatorAccess";
import { useAuthStore } from "../store/authStore";
import { ControlsPanel } from "./ops/ControlsPanel";
import { OpsTabPanel, OpsTabs, type OpsTab } from "./ops/OpsTabs";
import { TuningPanel } from "./ops/TuningPanel";
import { DatabaseCard, ProcessCard, QueuesCard, TrafficCard } from "./ops/OverviewSignals";
import {
  abandonmentRate,
  attentionReasons,
  readAuditLedger,
  readDailyTotals,
  readLiveSnapshot,
  readPlayerActivity,
  readRuntimeEvents,
  seriesFor,
  type AuditEntry,
  type DailyTotal,
  type LiveSnapshot,
  type RuntimeEventRow,
} from "../lib/operations";

// The live numbers are re-read this often while the overview is on screen.
// Same period as the clock that says "checked Ns ago", so the two agree.
const POLL_MS = 10_000;

const TRENDS = [
  { metric: "room.created", label: "Rooms opened" },
  { metric: "game.finished", label: "Games finished" },
  { metric: "game.abandoned", label: "Games abandoned" },
  { metric: "player.disconnected", label: "Disconnects" },
  { metric: "timer.overran", label: "Timer overruns" },
];

const CHART_DAYS = 14;

const TAB_IDS = "ops";

/** Which tab a link asked for, defaulting to the dashboard. */
function tabFromLocation(search: string): string {
  const asked = new URLSearchParams(search).get("tab");
  return TABS.some((candidate) => candidate.id === asked) ? asked! : "overview";
}

const TABS: readonly OpsTab[] = [
  { id: "overview", label: "Overview" },
  { id: "tuning", label: "Tuning" },
  { id: "controls", label: "Controls" },
  { id: "activity", label: "Activity" },
  { id: "audit", label: "Audit ledger" },
];

function shortTime(iso: string, timeFormat: TimeFormat): string {
  const then = new Date(iso);
  const now = new Date();
  if (then.toDateString() === now.toDateString()) {
    return formatClock(then, timeFormat);
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
  // `config.changed`, `maintenance.*` and the room commands are all things an
  // administrator did to a running server, and none of them carries "admin" in
  // its name - so without this they read as ordinary logged events beside a
  // retention sweep, which is exactly the wrong company for them.
  if (/admin|config|maintenance|^room\./.test(eventType)) {
    return { label: "Admin", kind: "primary" };
  }
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
  const { timeFormat, dateTime } = useClock();
  const [live, setLive] = useState<LiveSnapshot | null>(null);
  // Admission state, because the banner speaks for it. It used to say
  // "accepting rooms" unconditionally, which is the opposite of the truth
  // while a maintenance pause is on.
  const [maintenance, setMaintenance] = useState<MaintenanceState | null>(null);
  const [days, setDays] = useState<DailyTotal[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<RuntimeEventRow[]>([]);
  const [chartMetric, setChartMetric] = useState(TRENDS[0].metric);
  const [tab, setTab] = useState(() => tabFromLocation(window.location.search));
  const [eventFilter, setEventFilter] = useState("");
  const [roomFilter, setRoomFilter] = useState("");
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // When the live numbers were last asked for, by either path. Null until
  // `refresh` has run, so the first poll cannot double the fetch it makes.
  const lastPolledRef = useRef<number | null>(null);
  const [showIds, setShowIds] = useState(false);
  const [player, setPlayer] = useState<{
    displayName: string;
    events: RuntimeEventRow[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notices = useAdmissionNotices();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const allowed = hasResolved && canAdminister(user?.role);

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not load operator data.",
    );
  }, []);

  const refresh = useCallback(() => {
    // Not fetched before the role is known, or for somebody it would refuse:
    // firing four requests that answer 404 is noise in the log and a
    // confusing error on a page the visitor was never meant to see.
    if (!allowed) return;
    lastPolledRef.current = Date.now();
    void Promise.all([
      readLiveSnapshot(),
      readDailyTotals(),
      readAuditLedger({ limit: 200 }),
      readMaintenance(),
    ])
      .then(([metrics, daily, ledger, admission]) => {
        setLive(metrics);
        setDays(daily.days);
        setAudit(ledger.entries);
        setMaintenance(admission);
        setCheckedAt(Date.now());
        setError(null);
      })
      .catch(fail);
  }, [allowed, fail]);

  // Only the live snapshot is polled, only while the overview is the tab on
  // screen and the document is visible: a background tab asking every ten
  // seconds is exactly the load a dashboard should not be, and the daily
  // aggregates and the ledger do not change at that pace.
  useEffect(() => {
    if (tab !== "overview" || !allowed) return;
    if (document.visibilityState !== "visible") return;
    if (lastPolledRef.current === null) return;
    // Skipped only when a refresh landed within the last half-period, so a
    // tick that falls just short of ten seconds after one still polls.
    if (now - lastPolledRef.current < POLL_MS / 2) return;
    lastPolledRef.current = now;
    void readLiveSnapshot()
      .then((metrics) => {
        setLive(metrics);
        setCheckedAt(Date.now());
        setError(null);
      })
      .catch(fail);
  }, [now, tab, allowed, fail]);

  // Coming back to the tab re-reads at once rather than at the next tick.
  useEffect(() => {
    const wake = () => {
      if (document.visibilityState === "visible") setNow(Date.now());
    };
    document.addEventListener("visibilitychange", wake);
    return () => document.removeEventListener("visibilitychange", wake);
  }, []);

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

  // Re-read on every (re)connect as well as on mount: after a restart the
  // numbers and the admission state both belong to a process that is gone.
  useEffect(refresh, [refresh, notices.connection]);

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

  // Activity is fetched when its tab is first opened, not with the dashboard.
  // The raw event table is the expensive read on this page, and an operator
  // who came to look at a chart should not pay for it.
  useEffect(() => {
    if (tab === "activity" && events.length === 0) loadEvents();
  }, [tab, events.length, loadEvents]);

  // In the query string so a link to one tab survives being sent or reloaded.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (tab === "overview") url.searchParams.delete("tab");
    else url.searchParams.set("tab", tab);
    window.history.replaceState(null, "", url);
  }, [tab]);

  const rate = live ? abandonmentRate(live.games) : null;
  const chartLabel =
    TRENDS.find((trend) => trend.metric === chartMetric)?.label ?? chartMetric;
  const chartToday = useMemo(
    () => seriesFor(days, chartMetric).at(-1)?.value ?? 0,
    [days, chartMetric],
  );
  const checkedAgo =
    checkedAt === null ? null : Math.max(0, Math.round((now - checkedAt) / 1000));
  // One ordered list of what needs an operator, shared by the banner, the
  // attention paragraph, and the chip on every card - so they cannot disagree.
  const reasons = useMemo(() => (live ? attentionReasons(live) : []), [live]);
  const recorderHealthy = !reasons.some((reason) => reason.card === "recorder");
  // Corrected by what the server has announced since the last fetch, so a
  // pause or a drain started elsewhere does not leave this banner claiming
  // the server is taking rooms.
  const state = mergeAdmission(maintenance, notices);
  const admission = admissionLabel(state);
  const admitting = isAdmitting(state);
  if (hasResolved && !allowed) {
    // The same answer the API gives this account. A page that names the
    // surface and refuses it confirms the surface exists; R-ROLE-01 has every
    // endpoint behind these entries answer 404 rather than 403, and the door
    // in front of them should say the same thing.
    return <NotFoundPage />;
  }

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

      <OpsTabs tabs={TABS} current={tab} idPrefix={TAB_IDS} onSelect={setTab} />

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}

      <OpsTabPanel id="overview" current={tab} idPrefix={TAB_IDS}>
      {live && (
        <>
          <div
            className={`ops-status-banner${
              reasons.length === 0 && admitting ? "" : " is-warning"
            }`}
            role="status"
          >
            <span className="ops-status-dot" aria-hidden="true" />
            <strong>
              {reasons.length > 0
                ? reasons[0].headline
                : admitting
                  ? "All systems operational"
                  : "Not accepting new rooms"}
            </strong>
            <span>
              Single worker · {admission}
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

          <div className="ops-signals">
            <TrafficCard live={live} reasons={reasons} />
            <ProcessCard live={live} reasons={reasons} />
            <DatabaseCard live={live} reasons={reasons} />
            <QueuesCard live={live} reasons={reasons} />
          </div>

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
                {reasons.length === 0 ? (
                  <p>Nothing needs an operator.</p>
                ) : (
                  <ul>
                    {reasons.map((reason) => (
                      <li key={reason.key}>{reason.text}</li>
                    ))}
                  </ul>
                )}
              </div>
            </section>
          </div>

        </>
      )}
      </OpsTabPanel>

      <OpsTabPanel id="tuning" current={tab} idPrefix={TAB_IDS}>
        <TuningPanel />
      </OpsTabPanel>

      <OpsTabPanel id="controls" current={tab} idPrefix={TAB_IDS}>
        <ControlsPanel />
      </OpsTabPanel>

      <OpsTabPanel id="activity" current={tab} idPrefix={TAB_IDS}>
      <section className="ops-card ops-activity" aria-label="Recorded activity">
        <div className="ops-card-head">
          <div>
            <h2>Recorded activity</h2>
            <p className="ops-card-sub">
              Raw observations, before they are rolled into the daily totals
              the chart draws.
            </p>
          </div>
        </div>
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
                  <td>{dateTime(new Date(row.occurredAt))}</td>
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
      </section>
      </OpsTabPanel>

      <OpsTabPanel id="audit" current={tab} idPrefix={TAB_IDS}>
      <section className="ops-card ops-ledger" aria-label="Audit ledger">
        <div className="ops-card-head">
          <div>
            <h2>Audit ledger</h2>
            <p className="ops-card-sub">
              Every operator and automated action, newest first · append-only.
              Names are resolved as the ledger is read, so a deleted account
              reads as one while the entry stands exactly as it was.
            </p>
          </div>

        </div>
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
        {audit.length === 0 && (
          <p className="ops-empty">Nothing recorded yet.</p>
        )}
        {audit.map((entry) => {
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
              <time dateTime={entry.createdAt}>{shortTime(entry.createdAt, timeFormat)}</time>
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
      </OpsTabPanel>

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
                      <td>{dateTime(new Date(row.occurredAt))}</td>
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
