import { useClock } from "../../hooks/useClock";
import type { ReactNode } from "react";
import { Chip } from "../../components/ui/Chip";
import {
  formatBytes,
  formatDuration,
  formatMs,
  formatPercent,
  formatRate,
  poolFill,
  type AttentionCard,
  type AttentionReason,
  type LiveSnapshot,
  type PayloadSizeRow,
} from "../../lib/operations";
import { Sparkline } from "./Sparkline";

/** The four signal cards on the overview: what the worker is coping with,
as opposed to what it has done. Each card judges itself by the attention
reasons drawn from its own numbers, so the chip on a card and the banner at
the top of the page can never disagree about what is wrong. */

function Cell({
  label,
  value,
  note,
  warning = false,
  full = false,
  children,
}: {
  label: string;
  value: string;
  note?: string;
  warning?: boolean;
  /** Spans the grid: for a cell whose note is a path, not a number. */
  full?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`ops-signal${warning ? " is-warning" : ""}${full ? " ops-signal-full" : ""}`}>
      <span className="ops-signal-label">{label}</span>
      <span className="ops-signal-value">{value}</span>
      {note && <span className="ops-signal-note">{note}</span>}
      {children}
    </div>
  );
}

function SignalCard({
  title,
  sub,
  card,
  reasons,
  wide = false,
  children,
}: {
  title: string;
  sub: string;
  card: AttentionCard;
  reasons: AttentionReason[];
  /** Spans the whole signal row: the card with the most to say. */
  wide?: boolean;
  children: ReactNode;
}) {
  const healthy = !reasons.some((reason) => reason.card === card);
  return (
    <section className={`ops-card${wide ? " ops-card-wide" : ""}`} aria-label={title}>
      <div className="ops-card-head">
        <div>
          <h2>{title}</h2>
          <p className="ops-card-sub">{sub}</p>
        </div>
        <Chip kind={healthy ? "success" : "warm"}>{healthy ? "Healthy" : "Attention"}</Chip>
      </div>
      {children}
    </section>
  );
}

function flagged(reasons: AttentionReason[], key: string): boolean {
  return reasons.some((reason) => reason.key === key || reason.key.startsWith(`${key}:`));
}

export function TrafficCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
  const { http, socket, series, windowMinutes } = live;
  return (
    <SignalCard
      title="Traffic"
      sub={`Rates and latency over the last ${windowMinutes} min · sparklines cover an hour`}
      card="traffic"
      reasons={reasons}
      wide
    >
      <div className="ops-signal-grid ops-signal-row" role="group" aria-label="Requests">
        <Cell label="Requests / min" value={formatRate(http.perMinute)} note={`${http.inFlight} in flight`}>
          <Sparkline values={series.httpPerMinute} label="Requests per minute" format={formatRate} />
        </Cell>
        <Cell
          label="Request p95"
          value={formatMs(http.p95Ms)}
          note={`p50 ${formatMs(http.p50Ms)} · p99 ${formatMs(http.p99Ms)}`}
        >
          <Sparkline values={series.httpP95Ms} label="Request p95 latency" format={formatMs} />
        </Cell>
        <Cell
          label="Request errors"
          value={formatPercent(http.errorRate)}
          note={`${http.total.toLocaleString()} since start`}
          warning={flagged(reasons, "http-errors")}
        />
      </div>
      <div className="ops-signal-grid ops-signal-row" role="group" aria-label="Commands">
        <Cell label="Commands / min" value={formatRate(socket.perMinute)} note={`${socket.connected ?? "—"} sockets open`}>
          <Sparkline values={series.socketPerMinute} label="Client commands per minute" format={formatRate} />
        </Cell>
        <Cell label="Command p95" value={formatMs(socket.p95Ms)} note="handler time, per command">
          <Sparkline values={series.socketP95Ms} label="Command p95 latency" format={formatMs} />
        </Cell>
        <Cell
          label="Command errors"
          value={formatPercent(socket.errorRate)}
          note={`refused ${formatPercent(socket.refusedRate)} · throttled ${formatRate(socket.throttledPerMinute)}/min`}
          warning={flagged(reasons, "socket-errors")}
        />
      </div>
      <div className="ops-signal-grid ops-signal-row" role="group" aria-label="Sockets">
        <Cell
          label="Socket in / min"
          value={formatBytes(socket.bytesInPerMinute)}
          note={`${formatBytes(socket.bytesInTotal)} since start · before compression`}
        >
          <Sparkline values={series.socketBytesInPerMinute} label="Socket bytes received per minute" format={formatBytes} />
        </Cell>
        <Cell
          label="Socket out / min"
          value={formatBytes(socket.bytesOutPerMinute)}
          note={`${formatBytes(socket.bytesOutTotal)} since start · per recipient`}
        >
          <Sparkline values={series.socketBytesOutPerMinute} label="Socket bytes sent per minute" format={formatBytes} />
        </Cell>
      </div>
      <div className="ops-signal-grid ops-signal-row" role="group" aria-label="Socket envelopes">
        <Cell
          label="Rejected packets"
          value={sumCounts(socket.packetsRejected).toLocaleString()}
          note={byLabel(socket.packetsRejected) || "none since start · dropped before dispatch"}
          warning={sumCounts(socket.packetsRejected) > 0}
        />
        <Cell
          label="Connections by compression"
          value={sumCounts(socket.transports).toLocaleString()}
          note={byLabel(socket.transports) || "no WebSocket upgrades yet"}
        />
      </div>
      <div className="ops-sizes-row">
        <PayloadSizes title="Command payloads" rows={socket.commandSizes} />
        <PayloadSizes title="Emitted payloads" rows={socket.emitSizes} />
      </div>
    </SignalCard>
  );
}

function sumCounts(counts: Record<string, number>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0);
}

/** `reason 12 · other 3`, largest first; empty when there is nothing to say. */
function byLabel(counts: Record<string, number>): string {
  return Object.entries(counts)
    .sort(([, a], [, b]) => b - a)
    .map(([label, count]) => `${label} ${count.toLocaleString()}`)
    .join(" · ");
}

/** What each command or event weighs, largest total first, since start.

Sizes are the payload as the handler saw it, before framing and compression:
the right number for "which command is the chatty one", not for a bill. */
function PayloadSizes({ title, rows }: { title: string; rows: PayloadSizeRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="ops-sizes">
      <h3>{title}</h3>
      <table className="ops-size-table">
        <thead>
          <tr>
            <th scope="col">Event</th>
            <th scope="col">Count</th>
            <th scope="col">p50</th>
            <th scope="col">p95</th>
            <th scope="col">p99</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.event}>
              <th scope="row">{row.event}</th>
              <td>{row.count.toLocaleString()}</td>
              <td>{formatBytes(row.p50)}</td>
              <td>{formatBytes(row.p95)}</td>
              <td>{formatBytes(row.p99)}</td>
              <td>{formatBytes(row.bytesTotal)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProcessCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
  const { dateTime } = useClock();
  const { process, series } = live;
  const lagWarning = flagged(reasons, "loop-lag");
  return (
    <SignalCard title="Process" sub="One worker: the event loop, its memory, and its disk" card="process" reasons={reasons}>
      <div className="ops-signal-grid">
        <Cell
          label="Loop lag"
          value={formatMs(process.loopLagMs)}
          note={`p95 ${formatMs(process.loopLagP95Ms)}`}
          warning={lagWarning}
        >
          <Sparkline values={series.loopLagMaxMs} label="Event-loop lag, worst per minute" format={formatMs} warning={lagWarning} />
        </Cell>
        <Cell
          label="CPU"
          value={process.cpuPercent === null ? "—" : `${process.cpuPercent.toFixed(1)} %`}
          note="of one core"
        />
        <Cell
          label={process.rssIsPeak ? "Memory (peak)" : "Memory"}
          value={formatBytes(process.rssBytes)}
          note="resident set size"
        >
          <Sparkline values={series.rssBytes} label="Resident memory" format={formatBytes} />
        </Cell>
        <Cell label="Uptime" value={formatDuration(process.uptimeSeconds)} note={`since ${dateTime(new Date(process.startedAt))}`} />
        <Cell
          label="Disk free"
          value={formatBytes(process.diskFreeBytes)}
          note={`of ${formatBytes(process.diskTotalBytes)} at ${process.diskPath}`}
          full
        />
      </div>
    </SignalCard>
  );
}

export function DatabaseCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
  const { database } = live;
  const fill = poolFill(database.pool);
  const lost = database.historyWritesAbandoned;
  const readiness = database.readiness;
  return (
    <SignalCard title="Database" sub="Pool, statement latency, and what was lost" card="database" reasons={reasons}>
      <div className="ops-signal-grid">
        <Cell
          label="Pool in use"
          value={database.pool ? `${database.pool.checkedOut} / ${database.pool.capacity}` : "—"}
          note={
            database.pool
              ? `${fill === null ? "" : `${Math.round(fill * 100)} % · `}${database.pool.overflow} overflow`
              : "no pool on this engine"
          }
          warning={flagged(reasons, "pool-saturated")}
        />
        <Cell label="Queries / min" value={formatRate(database.queriesPerMinute)} note={`${database.queryErrors} errors since start`} />
        <Cell label="Query p95" value={formatMs(database.queryP95Ms)} note="per statement" />
        <Cell
          label="History writes lost"
          value={String(lost.lastHour)}
          note={`last hour · ${lost.total} since start (${lost.byReason.timeout} timed out, ${lost.byReason.error} failed, ${lost.byReason.conflict + lost.byReason.exhausted + lost.byReason.unreadable} given up in replay)`}
          warning={flagged(reasons, "history-lost")}
        />
        <Cell
          label="Drawings stored"
          value={live.drawingStore ? formatBytes(live.drawingStore.totalBytes) : "—"}
          note={
            live.drawingStore
              ? `${live.drawingStore.readyRows.toLocaleString()} drawings · reopens object storage past 50 GB`
              : "no relation sizes on this engine"
          }
          warning={flagged(reasons, "drawing-store-large")}
        />
        <Cell
          label="Games staged"
          value={String(database.historyHandoff.staged)}
          note={`since start · replays: ${
            Object.entries(database.historyHandoff.replays)
              .map(([outcome, count]) => `${count} ${outcome.replaceAll("_", " ")}`)
              .join(", ") || "none yet"
          }`}
        />
      </div>
      <div className={`ops-health-row${readiness && !readiness.ok ? " is-warning" : ""}`}>
        <span className="ops-health-dot" aria-hidden="true" />
        <strong>Readiness probe</strong>
        <span>
          {readiness === null
            ? "not probed yet"
            : readiness.ok
              ? `reached the database ${formatDuration(readiness.checkedAgoSeconds)} ago`
              : (readiness.reason ?? "failed")}
        </span>
      </div>
    </SignalCard>
  );
}

/** Per-table retention compliance (#478).
 *
 *  A loop that runs is not a policy that is kept: what this card shows is
 *  what each sweep *left* behind - how far past its allowance the oldest row
 *  it should already have removed is, and how many are waiting. A table that
 *  owes nothing says so, because "no number" and "nothing overdue" have to
 *  look different for the panel to be worth reading. */
export function RetentionCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
  const tables = live.retention ?? [];
  return (
    <SignalCard
      title="Retention"
      sub="What each table still owes, against the deletion SLA it is held to"
      card="retention"
      reasons={reasons}
      wide
    >
      {tables.map((table) => (
        <div
          key={table.table}
          className={`ops-health-row${table.failed || table.breached ? " is-warning" : ""}`}
        >
          <span className="ops-health-dot" aria-hidden="true" />
          <strong className="ops-loop-name">{table.table}</strong>
          <span>
            {table.failed
              ? "last sweep failed"
              : table.overdueSeconds === null
                ? "backlog not measured"
                : table.overdueSeconds > 0
                  ? `oldest overdue ${formatDuration(table.overdueSeconds)}`
                  : "nothing overdue"}
            {table.slaSeconds !== null && ` · SLA ${formatDuration(table.slaSeconds)}`}
            {table.backlogRows ? ` · ${table.backlogRows} waiting` : ""}
            {table.exhausted && " · budget spent"}
            {table.removedTotal ? ` · ${table.removedTotal} removed since start` : ""}
            {table.failuresTotal ? ` · ${table.failuresTotal} failures since start` : ""}
          </span>
        </div>
      ))}
      {tables.length === 0 && <p className="ops-empty">The retention loop has not finished a pass yet.</p>}
    </SignalCard>
  );
}

export function QueuesCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
  const { queues } = live;
  const loops = Object.entries(live.loops).sort(([left], [right]) => left.localeCompare(right));
  return (
    <SignalCard title="Queues and loops" sub="Work written down for later, and the loops that carry it out" card="queues" reasons={reasons}>
      <div className={`ops-health-row${flagged(reasons, "mail-backlog") ? " is-warning" : ""}`}>
        <span className="ops-health-dot" aria-hidden="true" />
        <strong>Mail outbox</strong>
        <span>
          {queues.mailOutbox.pending} pending
          {queues.mailOutbox.oldestSeconds !== null && ` · oldest ${formatDuration(queues.mailOutbox.oldestSeconds)}`}
          {` · swept every ${formatDuration(queues.mailOutbox.sweepSeconds)}`}
        </span>
      </div>
      <div className={`ops-health-row${flagged(reasons, "export-stuck") ? " is-warning" : ""}`}>
        <span className="ops-health-dot" aria-hidden="true" />
        <strong>Account exports</strong>
        <span>
          {queues.dataExports.pending} pending
          {queues.dataExports.oldestSeconds !== null && ` · oldest ${formatDuration(queues.dataExports.oldestSeconds)}`}
        </span>
      </div>
      <div className={`ops-health-row${flagged(reasons, "history-backlog") || flagged(reasons, "history-failed") ? " is-warning" : ""}`}>
        <span className="ops-health-dot" aria-hidden="true" />
        <strong>Finished games</strong>
        <span>
          {queues.finishedGames.pending} staged
          {queues.finishedGames.oldestSeconds !== null && ` · oldest ${formatDuration(queues.finishedGames.oldestSeconds)}`}
          {queues.finishedGames.failed > 0 && ` · ${queues.finishedGames.failed} failed`}
          {` · swept every ${formatDuration(queues.finishedGames.sweepSeconds)}`}
        </span>
      </div>
      {loops.map(([name, loop]) => {
        const warning = !loop.running || loop.consecutiveFailures > 0;
        return (
          <div key={name} className={`ops-health-row${warning ? " is-warning" : ""}`}>
            <span className="ops-health-dot" aria-hidden="true" />
            <strong className="ops-loop-name">{name}</strong>
            <span>
              {!loop.running
                ? "stopped"
                : loop.consecutiveFailures > 0
                  ? `failing · ${loop.consecutiveFailures} in a row`
                  : loop.secondsSinceSuccess === null
                    ? "not yet run"
                    : `ok ${formatDuration(loop.secondsSinceSuccess)} ago`}
              {loop.totalFailures > 0 && loop.running && loop.consecutiveFailures === 0 && ` · ${loop.totalFailures} failures since start`}
            </span>
          </div>
        );
      })}
      {loops.length === 0 && <p className="ops-empty">No supervised loops reported.</p>}
    </SignalCard>
  );
}
