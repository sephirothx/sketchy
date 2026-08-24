import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import {
  createUserBan,
  listModerationReports,
  listPromptContentReports,
  reviewModerationReport,
  reviewPromptContentReport,
  type PlayerReport,
  type PromptContentReport,
  type ReportStatus,
} from "../lib/moderation";
import { canModerate } from "../lib/operatorAccess";
import { useAuthStore } from "../store/authStore";

type Queue = "players" | "content";

function formatWhen(value: string): string {
  return new Date(value).toLocaleString();
}

/** Where reports are read and acted on.

The API and its client have existed since #340; nothing called them, so every
report submitted so far has been written to a queue nobody could open. This is
the queue.

Reviewing is deliberately two decisions, not one. Resolving a content report
records that it was looked at; hiding the list or prompt is what acts on it,
and a moderator should have to mean both. */
export function ModerationPage() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [queue, setQueue] = useState<Queue>("players");
  const [status, setStatus] = useState<ReportStatus>("pending");
  const [players, setPlayers] = useState<PlayerReport[]>([]);
  const [content, setContent] = useState<PromptContentReport[]>([]);
  const [note, setNote] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
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
    } else {
      void listPromptContentReports(status)
        .then((result) => {
          setContent(result.reports);
          setError(null);
        })
        .catch(fail);
    }
  }, [allowed, queue, status, fail]);

  useEffect(load, [load]);

  if (hasResolved && !allowed) {
    return (
      <main className="ops-page">
        <Link to="/" className="back-link">← Back to lobby</Link>
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
      <header className="ops-header">
        <Link to="/" className="back-link">← Back to lobby</Link>
        <h1>Moderation</h1>
        <nav className="ops-tabs" aria-label="Report queues">
          {(["players", "content"] as Queue[]).map((name) => (
            <button
              key={name}
              type="button"
              className={queue === name ? "is-active" : undefined}
              aria-current={queue === name ? "page" : undefined}
              onClick={() => setQueue(name)}
            >
              {name === "players" ? "Player reports" : "Prompt content"}
            </button>
          ))}
        </nav>
      </header>

      <div className="ops-filters">
        <label htmlFor="mod-status">Showing</label>
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
                      <button
                        type="button"
                        className="mod-danger"
                        disabled={busy === report.id}
                        onClick={() =>
                          act(
                            report.id,
                            () =>
                              createUserBan({
                                userId: report.reportedUserId as string,
                                reason: note[report.id],
                              }),
                            "Suspended. They are signed out everywhere, and told why if they have a confirmed address.",
                          )
                        }
                      >
                        Suspend account
                      </button>
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
