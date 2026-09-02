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
  children,
}: {
  label: string;
  value: string;
  note?: string;
  warning?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`ops-signal${warning ? " is-warning" : ""}`}>
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
  children,
}: {
  title: string;
  sub: string;
  card: AttentionCard;
  reasons: AttentionReason[];
  children: ReactNode;
}) {
  const healthy = !reasons.some((reason) => reason.card === card);
  return (
    <section className="ops-card" aria-label={title}>
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
    >
      <div className="ops-signal-grid">
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
    </SignalCard>
  );
}

export function ProcessCard({ live, reasons }: { live: LiveSnapshot; reasons: AttentionReason[] }) {
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
        <Cell label="Uptime" value={formatDuration(process.uptimeSeconds)} note={`since ${new Date(process.startedAt).toLocaleString()}`} />
        <Cell
          label="Disk free"
          value={formatBytes(process.diskFreeBytes)}
          note={`of ${formatBytes(process.diskTotalBytes)} at ${process.diskPath}`}
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
          note={`last hour · ${lost.total} since start (${lost.byReason.timeout} timed out, ${lost.byReason.error} failed)`}
          warning={flagged(reasons, "history-lost")}
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
