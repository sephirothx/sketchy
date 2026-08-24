import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import {
  abandonmentRate,
  readAuditLedger,
  readDailyTotals,
  readLiveMetrics,
  readPlayerActivity,
  readRuntimeEvents,
  seriesFor,
  sparklinePoints,
  type AuditEntry,
  type DailyTotal,
  type LiveMetrics,
  type RuntimeEventRow,
} from "../lib/operations";

type Tab = "overview" | "events" | "audit";

const TRENDS = [
  { metric: "room.created", label: "Rooms opened" },
  { metric: "game.finished", label: "Games finished" },
  { metric: "game.abandoned", label: "Games abandoned" },
  { metric: "player.disconnected", label: "Disconnects" },
  { metric: "timer.overran", label: "Timer overruns" },
];

function Sparkline({ days, metric }: { days: DailyTotal[]; metric: string }) {
  const series = seriesFor(days, metric);
  const points = sparklinePoints(series, 160, 36);
  const latest = series.at(-1)?.value ?? 0;
  return (
    <div className="ops-trend">
      <div className="ops-trend-head">
        <span className="ops-trend-value">{latest}</span>
        <span className="ops-trend-window">today</span>
      </div>
      {points ? (
        <svg
          viewBox="0 0 160 36"
          className="ops-sparkline"
          role="img"
          aria-label={`${metric} over the retained window`}
        >
          <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      ) : (
        <p className="ops-empty">Nothing recorded yet.</p>
      )}
    </div>
  );
}

/** The operator's view of the server.

Everything here was unknowable before: `RoomManager` had the instrumentation
points and counted nothing at any of them. Live counts come from the worker's
own memory, which is exact because one worker owns everything; the trends come
from permanent daily aggregates, which outlive the raw rows behind them. */
export function AdminOperationsPage() {
  const [tab, setTab] = useState<Tab>("overview");
  const [live, setLive] = useState<LiveMetrics | null>(null);
  const [days, setDays] = useState<DailyTotal[]>([]);
  const [events, setEvents] = useState<RuntimeEventRow[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [eventFilter, setEventFilter] = useState("");
  const [roomFilter, setRoomFilter] = useState("");
  const [player, setPlayer] = useState<{
    displayName: string;
    events: RuntimeEventRow[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Names make the ledger readable; ids make it precise. Which one you need
  // depends on whether you are reading it or acting on it, so it is a switch
  // rather than a decision made for you.
  const [showIds, setShowIds] = useState(false);

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not load operator data.",
    );
  }, []);

  const loadOverview = useCallback(() => {
    void Promise.all([readLiveMetrics(), readDailyTotals()])
      .then(([metrics, daily]) => {
        setLive(metrics);
        setDays(daily.days);
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

  const loadAudit = useCallback(() => {
    void readAuditLedger({ limit: 200 })
      .then((result) => {
        setAudit(result.entries);
        setError(null);
      })
      .catch(fail);
  }, [fail]);

  useEffect(() => {
    if (tab === "overview") loadOverview();
    if (tab === "events") loadEvents();
    if (tab === "audit") loadAudit();
  }, [tab, loadOverview, loadEvents, loadAudit]);

  function inspect(userId: string | null) {
    if (!userId) return;
    void readPlayerActivity(userId)
      .then((result) =>
        setPlayer({ displayName: result.player.displayName, events: result.events }),
      )
      .catch(fail);
  }

  const rate = live ? abandonmentRate(live.games) : null;

  return (
    <main className="ops-page">
      <header className="ops-header">
        {/* These pages are reached from the account menu and have none of the
            game's chrome, so without this there is no way out but the browser
            button. Same affordance the other standalone pages use. */}
        <Link to="/" className="back-link">← Back to lobby</Link>
        <h1>Server operations</h1>
        <nav className="ops-tabs" aria-label="Operator views">
          {(["overview", "events", "audit"] as Tab[]).map((name) => (
            <button
              key={name}
              type="button"
              className={tab === name ? "is-active" : undefined}
              aria-current={tab === name ? "page" : undefined}
              onClick={() => setTab(name)}
            >
              {name === "overview"
                ? "Overview"
                : name === "events"
                  ? "Activity"
                  : "Audit ledger"}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}

      {tab === "overview" && live && (
        <>
          <section className="ops-tiles" aria-label="Live counts">
            <div className="ops-tile">
              <span className="ops-tile-label">Rooms</span>
              <span className="ops-tile-value">{live.live.rooms}</span>
              <span className="ops-tile-note">peak {live.peak.rooms}</span>
            </div>
            <div className="ops-tile">
              <span className="ops-tile-label">Players</span>
              <span className="ops-tile-value">{live.live.players}</span>
              <span className="ops-tile-note">peak {live.peak.players}</span>
            </div>
            <div className="ops-tile">
              <span className="ops-tile-label">Games running</span>
              <span className="ops-tile-value">{live.live.activeGames}</span>
              <span className="ops-tile-note">peak {live.peak.activeGames}</span>
            </div>
            <div
              className={`ops-tile${rate !== null && rate >= 25 ? " is-warning" : ""}`}
            >
              <span className="ops-tile-label">Abandoned</span>
              <span className="ops-tile-value">
                {rate === null ? "—" : `${rate}%`}
              </span>
              <span className="ops-tile-note">
                {live.games.abandoned} of{" "}
                {live.games.finished + live.games.abandoned + live.games.shutdown}
              </span>
            </div>
          </section>

          <section className="ops-trends" aria-label="Recent trends">
            {TRENDS.map(({ metric, label }) => (
              <div key={metric} className="ops-trend-card">
                <h2>{label}</h2>
                <Sparkline days={days} metric={metric} />
              </div>
            ))}
          </section>

          <section className="ops-recorder" aria-label="Recorder health">
            <h2>Recorder</h2>
            <p>
              {live.recorder.storedEvents} observations stored,{" "}
              {live.recorder.buffered} waiting to be written.
              {live.recorder.dropped > 0 && (
                <strong>
                  {" "}
                  {live.recorder.dropped} were dropped by a full buffer.
                </strong>
              )}
            </p>
          </section>
        </>
      )}

      {tab === "events" && (
        <section aria-label="Recorded activity">
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
            <button type="button" onClick={loadEvents}>
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
          {events.length === 0 && <p className="ops-empty">Nothing recorded yet.</p>}
        </section>
      )}

      {tab === "audit" && (
        <section aria-label="Audit ledger">
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
          <div className="ops-table-scroll">
            <table className="ops-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Subject</th>
                  <th scope="col">Actor</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((entry) => (
                  <tr key={entry.id}>
                    <td>{new Date(entry.createdAt).toLocaleString()}</td>
                    <td>{entry.eventType}</td>
                    <td>
                      {entry.targetType ? (
                        <>
                          <span className="ops-subject-kind">
                            {entry.targetType.replace(/_/g, " ")}
                          </span>{" "}
                          <span
                            className={showIds ? "ops-identifier" : undefined}
                            title={
                              (showIds ? entry.targetName : entry.targetId) ??
                              undefined
                            }
                          >
                            {showIds
                              ? (entry.targetId ?? "—")
                              : (entry.targetName ?? entry.targetId ?? "—")}
                          </span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td
                      className={showIds ? "ops-identifier" : undefined}
                      title={
                        (showIds ? entry.actorName : entry.actorUserId) ??
                        undefined
                      }
                    >
                      {showIds
                        ? (entry.actorUserId ?? "system")
                        : (entry.actorName ??
                          (entry.actorUserId ? "Deleted player" : "system"))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {audit.length === 0 && <p className="ops-empty">Nothing recorded yet.</p>}
        </section>
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
