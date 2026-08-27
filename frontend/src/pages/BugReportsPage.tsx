import { useCallback, useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Chip } from "../components/ui/Chip";
import { SectionLabel } from "../components/ui/Card";
import { CopyIcon } from "../components/icons";
import { ApiError } from "../lib/api";
import {
  bugReportScreenshotUrl,
  bugReportTriageText,
  copyToClipboard,
  humanizeBugValue,
  listBugReports,
  reviewBugReport,
  type BugReport,
  type BugReportStatus,
} from "../lib/bugReports";
import { canAdminister } from "../lib/operatorAccess";
import { useToast } from "../lib/toast";
import { useAuthStore } from "../store/authStore";

function formatWhen(value: string): string {
  return new Date(value).toLocaleString();
}

function age(value: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / (60 * 24))}d`;
}

function bytes(size: number | null): string {
  if (!size) return "—";
  return size < 1024 * 1024
    ? `${Math.round(size / 1024)} KB`
    : `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

/** Red blocks play, amber is major, grey is minor - the queue reads at a
    glance because severity is the only thing carried by color. */
const SEVERITY_DOT: Record<string, string> = {
  blocks_play: " is-danger",
  major: "",
  minor: " is-neutral",
};

const FILTERS: { name: BugReportStatus; label: string }[] = [
  { name: "pending", label: "Open" },
  { name: "resolved", label: "Resolved" },
  { name: "dismissed", label: "Dismissed" },
];

/** Where filed bugs are read and decided.
 *
 * Administrators only, and 404 to everybody else - the endpoints re-check that
 * for themselves, so this decides what to show rather than what to allow.
 */
export function BugReportsPage() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const notify = useToast().notify;

  const [status, setStatus] = useState<BugReportStatus>("pending");
  const [reports, setReports] = useState<BugReport[]>([]);
  const [openCount, setOpenCount] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const allowed = hasResolved && canAdminister(user?.role);

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError ? problem.message : "Could not reach the bug queue.",
    );
  }, []);

  const load = useCallback(() => {
    if (!allowed) return;
    void Promise.all([
      listBugReports(status),
      // The chip counts open work whatever is being viewed.
      status === "pending" ? Promise.resolve(null) : listBugReports("pending"),
    ])
      .then(([viewed, pending]) => {
        setReports(viewed.reports);
        setOpenCount((pending ?? viewed).reports.length);
        setError(null);
      })
      .catch(fail);
  }, [allowed, status, fail]);

  useEffect(load, [load]);

  // Derived rather than synced by an effect: whatever was clicked wins while it
  // is still in the queue, and the newest entry stands in otherwise.
  const active = useMemo(() => {
    const chosen = reports.find((report) => report.id === selectedId);
    return chosen ?? reports[0] ?? null;
  }, [reports, selectedId]);

  if (hasResolved && !allowed) {
    return (
      <main className="ops-page">
        <AppHeader backLabel="Back to lobby" />
        <h1>Bug reports</h1>
        <p className="ops-empty">This page is for administrators.</p>
      </main>
    );
  }

  async function decide(report: BugReport, decision: Exclude<BugReportStatus, "pending">) {
    if (busy) return;
    if (!note[report.id]?.trim()) {
      setError("A note is required, so the decision is not anonymous.");
      return;
    }
    setBusy(report.id);
    setError(null);
    try {
      await reviewBugReport(report.id, decision, note[report.id].trim());
      notify(`Report ${decision}. Its screenshot has been erased.`, "success");
      setNote((current) => ({ ...current, [report.id]: "" }));
      load();
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  async function copyForTriage(report: BugReport) {
    if (await copyToClipboard(bugReportTriageText(report))) {
      notify("Report copied as Markdown.", "success");
      return;
    }
    setError("This browser would not let the page write to the clipboard.");
  }

  const clientErrors = Array.isArray(active?.clientContext.recentErrors)
    ? (active.clientContext.recentErrors as { at: string; kind: string; message: string }[])
    : [];

  return (
    <main className="ops-page">
      <AppHeader backLabel="Back to lobby" />

      {error && <p className="auth-error" role="alert">{error}</p>}

      <div className="mod-layout">
        <aside className="ops-card mod-queue" aria-label="Bug report queue">
          <div className="mod-queue-head">
            <div>
              <SectionLabel>Administrators only</SectionLabel>
              <h2>Bug reports</h2>
            </div>
            <Chip kind={openCount > 0 ? "warning" : "success"}>{openCount} open</Chip>
          </div>
          <div className="mod-filters" role="group" aria-label="Which reports to show">
            {FILTERS.map(({ name, label }) => (
              <button
                key={name}
                type="button"
                className="mod-filter-pill"
                aria-pressed={status === name}
                onClick={() => setStatus(name)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="mod-queue-list">
            {reports.length === 0 && <p className="ops-empty">Nothing in this queue.</p>}
            {reports.map((report) => {
              const isSelected = active?.id === report.id;
              return (
                <button
                  key={report.id}
                  type="button"
                  className={`mod-queue-item${isSelected ? " is-selected" : ""}`}
                  aria-current={isSelected || undefined}
                  onClick={() => setSelectedId(report.id)}
                >
                  <span className={`mod-queue-dot${SEVERITY_DOT[report.severity] ?? ""}`} aria-hidden="true" />
                  <span className="mod-queue-item-text">
                    <strong>{report.summary}</strong>
                    <span>
                      {humanizeBugValue(report.area)} · {humanizeBugValue(report.severity).toLowerCase()}
                      {report.reporter ? ` · ${report.reporter.displayName}` : ""}
                      {report.screenshot.status === "ready" ? " · has a screenshot" : ""}
                    </span>
                  </span>
                  <time dateTime={report.createdAt}>{age(report.createdAt)}</time>
                </button>
              );
            })}
          </div>
          <p className="mod-note-hint">
            Sorted newest first. A player may file several — unrelated bugs are not
            one complaint repeated.
          </p>
        </aside>

        <div className="mod-case">
          {!active && <p className="ops-empty">Select a report to read it.</p>}
          {active && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>Bug report · #{active.id.slice(0, 8)}</SectionLabel>
                  <h1>{active.summary}</h1>
                  <p className="mod-case-meta">
                    {active.reporter
                      ? `From ${active.reporter.displayName} (${active.reporter.registered ? "registered" : "guest"})`
                      : "From a deleted account"}
                    {" · "}{formatWhen(active.createdAt)}
                    {active.buildSha ? ` · build ${active.buildSha}` : ""}
                  </p>
                </div>
                <div className="bug-case-actions">
                  <div className="bug-case-chips">
                    <Chip kind="primary">{humanizeBugValue(active.area)}</Chip>
                    <Chip kind={active.severity === "blocks_play" ? "danger" : active.severity === "major" ? "warning" : "neutral"}>
                      {humanizeBugValue(active.severity)}
                    </Chip>
                  </div>
                  <button type="button" className="bug-copy-button" onClick={() => void copyForTriage(active)}>
                    <CopyIcon size={15} aria-hidden="true" />
                    Copy for triage
                  </button>
                </div>
              </div>

              <div className={`bug-case-grid${active.screenshot.status === "none" ? " is-single" : ""}`}>
                <section className="ops-card">
                  <h2>What happened</h2>
                  <p className="bug-case-details">{active.details}</p>
                  {clientErrors.length > 0 && (
                    <>
                      <h2>Client errors at the time</h2>
                      <ul className="bug-console-log">
                        {clientErrors.map((entry, index) => (
                          <li key={`${entry.at}-${index}`}>
                            <span>{entry.at.slice(11, 19)}</span>{entry.kind} {entry.message}
                          </li>
                        ))}
                      </ul>
                      <p className="mod-note-hint">
                        Collected by the reporter's browser and sent with the report.
                        Evidence supplied by a player, not a fact the server checked.
                      </p>
                    </>
                  )}
                </section>

                {active.screenshot.status !== "none" && (
                  <aside className="ops-card">
                    <div className="bug-shot-head">
                      <h2>Screenshot</h2>
                      <Chip kind="neutral">{bytes(active.screenshot.byteSize)}</Chip>
                    </div>
                    {active.screenshot.status === "ready" ? (
                      <>
                        <a href={bugReportScreenshotUrl(active.id)} target="_blank" rel="noreferrer">
                          <img
                            className="bug-shot"
                            src={bugReportScreenshotUrl(active.id)}
                            alt={`Screenshot attached to bug report ${active.id}`}
                          />
                        </a>
                        <p className="mod-note-hint">
                          Erased when this report is decided — the row stays, the
                          pixels do not.
                        </p>
                      </>
                    ) : (
                      <p className="ops-empty">Erased when this report was decided.</p>
                    )}
                  </aside>
                )}
              </div>

              {/* Diagnostics run across the width rather than down a column.
                  Nine short facts in a narrow aside became a very tall list,
                  and the one genuinely long value - the user agent - wrapped
                  into a paragraph. Across the width they read as a strip, and
                  the long one gets a cell wide enough to hold it.

                  They sit below the report itself: what the player wrote and
                  what they photographed is the case, and the machine detail is
                  what you turn to once you know what you are looking for. */}
              <section className="ops-card bug-diagnostics-card">
                <h2>Diagnostics</h2>
                <dl className="bug-diagnostics">
                  {highlights(active).map(([label, shown, wide]) => (
                    <div key={label} className={`bug-diagnostic${wide ? " is-wide" : ""}`}>
                      <dt>{label}</dt>
                      <dd>{shown}</dd>
                    </div>
                  ))}
                </dl>
                {/* Full width, because these are long flat lists: opening one
                    in a sidebar was the same problem again. */}
                <div className="bug-more-row">
                  <details className="bug-more-context">
                    <summary>Everything the server saw</summary>
                    <ContextList value={active.serverContext} />
                  </details>
                  <details className="bug-more-context">
                    <summary>Everything the client reported</summary>
                    <ContextList value={active.clientContext} skip={["recentErrors"]} />
                  </details>
                </div>
              </section>

              {active.status === "pending" ? (
                <>
                  <label className="mod-note">
                    Resolution note
                    <textarea
                      placeholder="What you found, in one line — required to decide"
                      value={note[active.id] ?? ""}
                      onChange={(change) =>
                        setNote((current) => ({ ...current, [active.id]: change.target.value }))
                      }
                    />
                    <span className="mod-note-hint">
                      Kept in the append-only audit ledger. Deciding is one-way — a
                      report gets one resolution, and its screenshot is erased.
                    </span>
                  </label>
                  <div className="mod-case-actions">
                    <button
                      type="button"
                      disabled={busy === active.id}
                      onClick={() => void decide(active, "dismissed")}
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      className="bug-resolve-button"
                      disabled={busy === active.id}
                      onClick={() => void decide(active, "resolved")}
                    >
                      Resolve
                    </button>
                  </div>
                </>
              ) : (
                <section className="ops-card">
                  <h2>{humanizeBugValue(active.status)}</h2>
                  <p className="mod-case-meta">{active.reviewedAt ? formatWhen(active.reviewedAt) : ""}</p>
                  <p className="bug-case-details">{active.resolutionNote}</p>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}

/** One value from a nested context blob, or null when it was not recorded.
 *
 * Every lookup is defensive: these blobs come from whatever build the reporter
 * was running, and a triage page that threw because an older client sent one
 * fewer key would fail exactly when it is needed.
 */
function at(blob: Record<string, unknown>, path: string): string | null {
  let node: unknown = blob;
  for (const key of path.split(".")) {
    if (node === null || typeof node !== "object") return null;
    node = (node as Record<string, unknown>)[key];
  }
  if (node === null || node === undefined) return null;
  return String(node);
}

/** What a reader wants before anything else: which build, which screen, what
 * the connection had been doing, and whose account filed it.
 *
 * The third element marks a value that needs more than one cell. Only the user
 * agent does - it is an order of magnitude longer than everything else here,
 * and giving it its own width is what stops it wrapping into a paragraph.
 */
function highlights(report: BugReport): [string, string, boolean?][] {
  const client = report.clientContext;
  const server = report.serverContext;
  const round = at(server, "game.roundNumber");
  const room = report.roomCode
    ? `${report.roomCode}${round ? ` · round ${round} of ${at(server, "game.roundsTotal")}` : ""}`
    : "Not in a room";
  const viewport = at(client, "viewport.width")
    ? `${at(client, "viewport.width")} × ${at(client, "viewport.height")} · ${at(client, "viewport.dpr")}×`
    : "—";
  const reconnects = at(client, "connection.reconnects") ?? "0";
  const skew = at(server, "clockSkewSeconds");
  return [
    ["Build", report.buildSha ?? "—"],
    ["Page", report.route ?? "—"],
    ["Room", room],
    ["Screen", viewport],
    [
      "Connection",
      `${at(client, "connection.connected") === "true" ? "connected" : "offline"}`
      + ` · ${reconnects} reconnect${reconnects === "1" ? "" : "s"} this visit`,
    ],
    [
      "Seat",
      at(server, "game.isDrawer") === "true"
        ? "Drawing"
        : at(server, "seat.isSpectator") === "true"
          ? "Spectating"
          : at(server, "game.id")
            ? "Guessing"
            : "—",
    ],
    ["Account", at(server, "account.registered") === "true" ? "Registered" : "Guest"],
    ["Clock skew", skew ? `${skew}s` : "—"],
    ["Browser", at(client, "browser.userAgent") ?? "—", true],
  ];
}

/** Nested diagnostics as flat `a.b.c` rows.
 *
 * Flat rather than a tree because triage scans for one line, and a collapsible
 * tree makes the reader open three things to find out the browser was Safari.
 */
function ContextList({
  value,
  skip = [],
}: {
  value: Record<string, unknown>;
  skip?: string[];
}) {
  const rows: [string, string][] = [];
  const walk = (node: unknown, prefix: string) => {
    if (node === null || node === undefined) return;
    if (Array.isArray(node)) {
      if (node.length) rows.push([prefix, JSON.stringify(node)]);
      return;
    }
    if (typeof node === "object") {
      for (const [key, child] of Object.entries(node as Record<string, unknown>)) {
        if (!prefix && skip.includes(key)) continue;
        walk(child, prefix ? `${prefix}.${key}` : key);
      }
      return;
    }
    rows.push([prefix, String(node)]);
  };
  walk(value, "");

  if (!rows.length) return <p className="ops-empty">Nothing recorded.</p>;
  return (
    <dl className="bug-context">
      {rows.map(([label, shown]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{shown}</dd>
        </div>
      ))}
    </dl>
  );
}
