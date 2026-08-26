import { useCallback, useEffect, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { SectionLabel } from "../components/ui/Card";

import { ApiError } from "../lib/api";
import {
  createUserBan,
  listModerationReports,
  listPromptContentReports,
  listUserBans,
  revokeUserBan,
  reviewModerationReport,
  reviewPromptContentReport,
  type PlayerReport,
  type PromptContentReport,
  suspensionExpiry,
  SUSPENSION_DURATIONS,
  type ReportStatus,
  type UserBan,
} from "../lib/moderation";
import { canModerate } from "../lib/operatorAccess";
import { useAuthStore } from "../store/authStore";

type Queue = "players" | "content" | "bans";

function formatWhen(value: string): string {
  return new Date(value).toLocaleString();
}


export function ModerationPage() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [queue, setQueue] = useState<Queue>("players");
  const [status, setStatus] = useState<ReportStatus>("pending");
  const [players, setPlayers] = useState<PlayerReport[]>([]);
  const [content, setContent] = useState<PromptContentReport[]>([]);
  const [bans, setBans] = useState<UserBan[]>([]);
  const [note, setNote] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [duration, setDuration] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const allowed = hasResolved && canModerate(user?.role);

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not reach the moderation queue.",
    );
  }, []);

  const load = useCallback(() => {
    if (!allowed) return;
    // Every write below happens in a callback rather than here: this runs from
    // an effect, and a state write during one is what the linter rejects.
    if (queue === "players") {
      void listModerationReports(status)
        .then((result) => {
          setPlayers(result.reports);
          setError(null);
        })
        .catch(fail);
    } else if (queue === "content") {
      void listPromptContentReports(status)
        .then((result) => {
          setContent(result.reports);
          setError(null);
        })
        .catch(fail);
    } else {
      // Everything, not only what is in force: a suspension that has been
      // lifted or has expired is part of the record of what was done.
      void listUserBans()
        .then((result) => {
          setBans(result.bans);
          setError(null);
        })
        .catch(fail);
    }
  }, [allowed, queue, status, fail]);

  useEffect(load, [load]);

  if (hasResolved && !allowed) {
    return (
      <main className="ops-page">
        <AppHeader backLabel="Back to lobby" />
        <h1>Moderation</h1>
        <p className="ops-empty">This page is for moderators.</p>
      </main>
    );
  }

  async function act(id: string, run: () => Promise<unknown>, done: string) {
    if (busy) return;
    if (!note[id]?.trim()) {
      setError("A note is required, so the decision is not anonymous.");
      return;
    }
    setBusy(id);
    setError(null);
    try {
      await run();
      setMessage(done);
      setNote((current) => ({ ...current, [id]: "" }));
      load();
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="ops-page">
      <AppHeader backLabel="Back to lobby" />
      <header className="ops-header">
        <SectionLabel>Moderation</SectionLabel>
        <h1>Review queue</h1>
        <nav className="ops-tabs" aria-label="Report queues">
          {(["players", "content", "bans"] as Queue[]).map((name) => (
            <button
              key={name}
              type="button"
              className={queue === name ? "is-active" : undefined}
              aria-current={queue === name ? "page" : undefined}
              onClick={() => setQueue(name)}
            >
              {name === "players"
                ? "Player reports"
                : name === "content"
                  ? "Prompt content"
                  : "Suspensions"}
            </button>
          ))}
        </nav>
      </header>

      <div className="ops-filters">
        {queue !== "bans" && <label htmlFor="mod-status">Showing</label>}
        {queue !== "bans" && (
          <select
            id="mod-status"
            className="settings-select"
            value={status}
            onChange={(change) => setStatus(change.target.value as ReportStatus)}
          >
            <option value="pending">Waiting for review</option>
            <option value="resolved">Resolved</option>
            <option value="dismissed">Dismissed</option>
          </select>
        )}
        <button type="button" onClick={load}>
          Refresh
        </button>
      </div>

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="ops-empty" role="status">
          {message}
        </p>
      )}

      {queue === "players" ? (
        players.length === 0 ? (
          <p className="ops-empty">Nothing in this queue.</p>
        ) : (
          <ul className="mod-list">
            {players.map((report) => (
              <li key={report.id} className="mod-report">
                <div className="mod-report-head">
                  <span className="mod-reason">{report.reason.replace(/_/g, " ")}</span>
                  <span className="mod-when">{formatWhen(report.createdAt)}</span>
                </div>
                <p className="mod-details">{report.details}</p>
                {report.messageEvidence.length > 0 && (
                  <ul className="mod-evidence">
                    {report.messageEvidence.map((line) => (
                      <li key={line.sourceMessageId}>
                        <strong>{line.senderDisplayName}:</strong> {line.text}
                        {/* The snapshot is the evidence. The live message may
                            have been deleted since, which is the point of
                            keeping one. */}
                        {!line.sourceAvailable && (
                          <em> — original no longer in the room</em>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {report.status === "pending" && (
                  <div className="mod-actions">
                    <input
                      aria-label="Resolution note"
                      placeholder="Why, in one line"
                      value={note[report.id] ?? ""}
                      onChange={(change) =>
                        setNote((current) => ({
                          ...current,
                          [report.id]: change.target.value,
                        }))
                      }
                    />
                    <button
                      type="button"
                      disabled={busy === report.id}
                      onClick={() =>
                        act(
                          report.id,
                          () =>
                            reviewModerationReport(
                              report.id,
                              "resolved",
                              note[report.id],
                            ),
                          "Resolved.",
                        )
                      }
                    >
                      Resolve
                    </button>
                    <button
                      type="button"
                      disabled={busy === report.id}
                      onClick={() =>
                        act(
                          report.id,
                          () =>
                            reviewModerationReport(
                              report.id,
                              "dismissed",
                              note[report.id],
                            ),
                          "Dismissed.",
                        )
                      }
                    >
                      Dismiss
                    </button>
                    {report.reportedUserId && (
                      <>
                      <button
                        type="button"
                        className="mod-danger"
                        disabled={busy === report.id}
                        onClick={() =>
                          act(
                            report.id,
                            async () => {
                              const expiresAt = suspensionExpiry(
                                duration[report.id] ?? "24h",
                              );
                              await createUserBan({
                                userId: report.reportedUserId as string,
                                reason: note[report.id],
                                // So the suspended player can be shown what
                                // the complaint was actually about.
                                reportId: report.id,
                                ...(expiresAt ? { expiresAt } : {}),
                              });
                              // Acting on a report decides it. Leaving it
                              // pending puts it back in front of the next
                              // moderator, to look at something already done.
                              await reviewModerationReport(
                                report.id,
                                "resolved",
                                note[report.id],
                              );
                            },
                            "Suspended, and the report resolved. They are signed out everywhere, and told why if they have a confirmed address.",
                          )
                        }
                      >
                        Suspend…
                      </button>
                      <select
                        aria-label="How long the suspension lasts"
                        className="settings-select"
                        value={duration[report.id] ?? "24h"}
                        onChange={(change) =>
                          setDuration((current) => ({
                            ...current,
                            [report.id]: change.target.value,
                          }))
                        }
                      >
                        {SUSPENSION_DURATIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      </>
                    )}
                  </div>
                )}
                {report.resolutionNote && (
                  <p className="mod-resolution">{report.resolutionNote}</p>
                )}
              </li>
            ))}
          </ul>
        )
      ) : queue === "bans" ? (
        bans.length === 0 ? (
          <p className="ops-empty">Nobody has been suspended.</p>
        ) : (
          <ul className="mod-list">
            {bans.map((ban) => (
              <li key={ban.id} className="mod-report">
                <div className="mod-report-head">
                  <span className="mod-reason">
                    {ban.displayName ?? "Deleted player"}
                  </span>
                  <span className="mod-when">{formatWhen(ban.createdAt)}</span>
                </div>
                <p className="mod-details">{ban.reason}</p>
                <p className="mod-subject">
                  {ban.isActive
                    ? ban.expiresAt
                      ? `In force until ${formatWhen(ban.expiresAt)}`
                      : "In force, with no end date"
                    : ban.revokedAt
                      ? `Lifted ${formatWhen(ban.revokedAt)}`
                      : "Expired"}
                </p>
                {ban.isActive && (
                  <div className="mod-actions">
                    <input
                      aria-label="Reason for lifting"
                      placeholder="Why, in one line"
                      value={note[ban.id] ?? ""}
                      onChange={(change) =>
                        setNote((current) => ({
                          ...current,
                          [ban.id]: change.target.value,
                        }))
                      }
                    />
                    <button
                      type="button"
                      disabled={busy === ban.id}
                      onClick={() =>
                        act(
                          ban.id,
                          () => revokeUserBan(ban.id, note[ban.id]),
                          "Lifted. They can sign in again.",
                        )
                      }
                    >
                      Lift suspension
                    </button>
                  </div>
                )}
                {ban.revokeReason && (
                  <p className="mod-resolution">{ban.revokeReason}</p>
                )}
              </li>
            ))}
          </ul>
        )
      ) : content.length === 0 ? (
        <p className="ops-empty">Nothing in this queue.</p>
      ) : (
        <ul className="mod-list">
          {content.map((report) => (
            <li key={report.id} className="mod-report">
              <div className="mod-report-head">
                <span className="mod-reason">{report.reason.replace(/_/g, " ")}</span>
                <span className="mod-when">{formatWhen(report.createdAt)}</span>
              </div>
              <p className="mod-subject">
                {report.targetType === "prompt" ? (
                  <>
                    Prompt <strong>{report.prompt}</strong> in {report.listName}
                  </>
                ) : (
                  <>
                    List <strong>{report.listName}</strong>
                  </>
                )}
              </p>
              <p className="mod-details">{report.details}</p>
              {report.status === "pending" && (
                <div className="mod-actions">
                  <input
                    aria-label="Resolution note"
                    placeholder="Why, in one line"
                    value={note[report.id] ?? ""}
                    onChange={(change) =>
                      setNote((current) => ({
                        ...current,
                        [report.id]: change.target.value,
                      }))
                    }
                  />
                  <button
                    type="button"
                    className="mod-danger"
                    disabled={busy === report.id}
                    onClick={() =>
                      act(
                        report.id,
                        () =>
                          reviewPromptContentReport(
                            report.id,
                            "resolved",
                            note[report.id],
                            "hidden",
                          ),
                        "Hidden, and the owner is told if they have a confirmed address.",
                      )
                    }
                  >
                    Hide it
                  </button>
                  <button
                    type="button"
                    disabled={busy === report.id}
                    onClick={() =>
                      act(
                        report.id,
                        () =>
                          reviewPromptContentReport(
                            report.id,
                            "resolved",
                            note[report.id],
                            "active",
                          ),
                        "Resolved, and left where it is.",
                      )
                    }
                  >
                    Leave it up
                  </button>
                  <button
                    type="button"
                    disabled={busy === report.id}
                    onClick={() =>
                      act(
                        report.id,
                        () =>
                          reviewPromptContentReport(
                            report.id,
                            "dismissed",
                            note[report.id],
                          ),
                        "Dismissed.",
                      )
                    }
                  >
                    Dismiss
                  </button>
                </div>
              )}
              {report.resolutionNote && (
                <p className="mod-resolution">{report.resolutionNote}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
