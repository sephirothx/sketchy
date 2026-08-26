import { useCallback, useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { Chip } from "../components/ui/Chip";
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

type Filter = "open" | "players" | "content" | "bans";
type CaseKind = "player" | "content" | "ban";
type Selection = { kind: CaseKind; id: string };

type QueueEntry = {
  kind: CaseKind;
  id: string;
  title: string;
  snippet: string;
  createdAt: string;
  dot: "danger" | "warning" | "neutral";
};

const FILTERS: { name: Filter; label: string }[] = [
  { name: "open", label: "All open" },
  { name: "players", label: "Player reports" },
  { name: "content", label: "Prompt content" },
  { name: "bans", label: "Suspensions" },
];

function formatWhen(value: string): string {
  return new Date(value).toLocaleString();
}

function age(value: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60000));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / (60 * 24))}d`;
}

function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function ModerationPage() {
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [filter, setFilter] = useState<Filter>("open");
  const [status, setStatus] = useState<ReportStatus>("pending");
  const [players, setPlayers] = useState<PlayerReport[]>([]);
  const [content, setContent] = useState<PromptContentReport[]>([]);
  const [bans, setBans] = useState<UserBan[]>([]);
  const [openCount, setOpenCount] = useState(0);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [note, setNote] = useState<Record<string, string>>({});
  const [duration, setDuration] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const allowed = hasResolved && canModerate(user?.role);
  // "All open" is always the pending work; the status select only applies to
  // the single-queue views, where looking back at decided cases makes sense.
  const effectiveStatus: ReportStatus = filter === "open" ? "pending" : status;

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not reach the moderation queue.",
    );
  }, []);

  const load = useCallback(() => {
    if (!allowed) return;
    void Promise.all([
      listModerationReports(effectiveStatus),
      listPromptContentReports(effectiveStatus),
      // Everything, not only what is in force: a suspension that has been
      // lifted or has expired is part of the record of what was done.
      listUserBans(),
      // The "N open" chip counts pending work whatever is being viewed.
      effectiveStatus === "pending"
        ? Promise.resolve(null)
        : Promise.all([
            listModerationReports("pending"),
            listPromptContentReports("pending"),
          ]),
    ])
      .then(([playerResult, contentResult, banResult, pendingResult]) => {
        setPlayers(playerResult.reports);
        setContent(contentResult.reports);
        setBans(banResult.bans);
        setOpenCount(
          pendingResult
            ? pendingResult[0].reports.length + pendingResult[1].reports.length
            : playerResult.reports.length + contentResult.reports.length,
        );
        setError(null);
      })
      .catch(fail);
  }, [allowed, effectiveStatus, fail]);

  useEffect(load, [load]);

  const queue = useMemo<QueueEntry[]>(() => {
    const playerEntries: QueueEntry[] = players.map((report) => ({
      kind: "player",
      id: report.id,
      title: humanize(report.reason),
      snippet: report.details,
      createdAt: report.createdAt,
      dot: "danger",
    }));
    const contentEntries: QueueEntry[] = content.map((report) => ({
      kind: "content",
      id: report.id,
      title: humanize(report.reason),
      snippet:
        report.targetType === "prompt"
          ? `Prompt “${report.prompt}” in ${report.listName ?? "a list"}`
          : `List “${report.listName}”`,
      createdAt: report.createdAt,
      dot: "warning",
    }));
    const banEntries: QueueEntry[] = bans.map((ban) => ({
      kind: "ban",
      id: ban.id,
      title: ban.displayName ?? "Deleted player",
      snippet: ban.reason,
      createdAt: ban.createdAt,
      dot: ban.isActive ? "danger" : "neutral",
    }));
    const entries =
      filter === "players"
        ? playerEntries
        : filter === "content"
          ? contentEntries
          : filter === "bans"
            ? banEntries
            : [...playerEntries, ...contentEntries];
    return entries.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  }, [filter, players, content, bans]);

  // Derived rather than synced by an effect: whatever is clicked wins while
  // it is still in the queue, and the newest entry stands in otherwise.
  const active: Selection | null = useMemo(() => {
    if (
      selected &&
      queue.some((entry) => entry.kind === selected.kind && entry.id === selected.id)
    ) {
      return selected;
    }
    return queue.length > 0 ? { kind: queue[0].kind, id: queue[0].id } : null;
  }, [queue, selected]);

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

  const playerCase =
    active?.kind === "player"
      ? players.find((report) => report.id === active.id)
      : undefined;
  const contentCase =
    active?.kind === "content"
      ? content.find((report) => report.id === active.id)
      : undefined;
  const banCase =
    active?.kind === "ban"
      ? bans.find((ban) => ban.id === active.id)
      : undefined;

  const noteField = (id: string) => (
    <label className="mod-note">
      Resolution note
      <textarea
        placeholder="Why, in one line — required to decide"
        value={note[id] ?? ""}
        onChange={(change) =>
          setNote((current) => ({ ...current, [id]: change.target.value }))
        }
      />
      <span className="mod-note-hint">
        Kept in the append-only audit ledger. A suspension from here also
        resolves this report.
      </span>
    </label>
  );

  return (
    <main className="ops-page">
      <AppHeader backLabel="Back to lobby" />

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

      <div className="mod-layout">
        <aside className="ops-card mod-queue" aria-label="Review queue">
          <div className="mod-queue-head">
            <div>
              <SectionLabel>Moderation</SectionLabel>
              <h2>Review queue</h2>
            </div>
            <Chip kind={openCount > 0 ? "danger" : "success"}>
              {openCount} open
            </Chip>
          </div>
          <div className="mod-filters" role="group" aria-label="Queues">
            {FILTERS.map(({ name, label }) => (
              <button
                key={name}
                type="button"
                className="mod-filter-pill"
                aria-pressed={filter === name}
                onClick={() => setFilter(name)}
              >
                {label}
              </button>
            ))}
          </div>
          {(filter === "players" || filter === "content") && (
            <select
              className="ops-select"
              aria-label="Which cases to show"
              value={status}
              onChange={(change) => setStatus(change.target.value as ReportStatus)}
            >
              <option value="pending">Waiting for review</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
            </select>
          )}
          <div className="mod-queue-list">
            {queue.length === 0 && (
              <p className="ops-empty">
                {filter === "bans"
                  ? "Nobody has been suspended."
                  : "Nothing in this queue."}
              </p>
            )}
            {queue.map((entry) => {
              const isSelected =
                active?.kind === entry.kind && active.id === entry.id;
              return (
                <button
                  key={`${entry.kind}:${entry.id}`}
                  type="button"
                  className={`mod-queue-item${isSelected ? " is-selected" : ""}`}
                  aria-current={isSelected || undefined}
                  onClick={() => setSelected({ kind: entry.kind, id: entry.id })}
                >
                  <span
                    className={`mod-queue-dot${
                      entry.dot === "danger"
                        ? " is-danger"
                        : entry.dot === "neutral"
                          ? " is-neutral"
                          : ""
                    }`}
                    aria-hidden="true"
                  />
                  <span className="mod-queue-item-text">
                    <strong>{entry.title}</strong>
                    <span>{entry.snippet}</span>
                  </span>
                  <time dateTime={entry.createdAt}>{age(entry.createdAt)}</time>
                </button>
              );
            })}
          </div>
        </aside>

        <div className="mod-case">
          {playerCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>
                    Player report · #{playerCase.id.slice(0, 6)}
                  </SectionLabel>
                  <h1>{humanize(playerCase.reason)}</h1>
                  <p className="mod-case-meta">
                    Reported {formatWhen(playerCase.createdAt)}
                  </p>
                </div>
                <Chip kind="danger">{humanize(playerCase.reason)}</Chip>
              </div>

              <section className="ops-card" aria-label="Reported evidence">
                <h2>Reported evidence</h2>
                {playerCase.details && (
                  <p className="mod-case-details">{playerCase.details}</p>
                )}
                {playerCase.messageEvidence.length > 0 && (
                  <>
                    <blockquote className="mod-evidence">
                      {playerCase.messageEvidence.map((line) => (
                        <span key={line.sourceMessageId}>
                          <strong>{line.senderDisplayName}:</strong> {line.text}
                          {/* The snapshot is the evidence. The live message may
                              have been deleted since, which is the point of
                              keeping one. */}
                          {!line.sourceAvailable && (
                            <em> — original no longer in the room</em>
                          )}
                        </span>
                      ))}
                    </blockquote>
                    <p className="mod-evidence-caption">
                      Pinned by the server exactly as the reporter received them
                      — up to 20 messages.
                    </p>
                  </>
                )}
              </section>

              {playerCase.status === "pending" ? (
                <>
                  {noteField(playerCase.id)}
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy === playerCase.id}
                      onClick={() =>
                        act(
                          playerCase.id,
                          () =>
                            reviewModerationReport(
                              playerCase.id,
                              "dismissed",
                              note[playerCase.id],
                            ),
                          "Dismissed.",
                        )
                      }
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={busy === playerCase.id}
                      onClick={() =>
                        act(
                          playerCase.id,
                          () =>
                            reviewModerationReport(
                              playerCase.id,
                              "resolved",
                              note[playerCase.id],
                            ),
                          "Resolved.",
                        )
                      }
                    >
                      Resolve
                    </button>
                    {playerCase.reportedUserId && (
                      <>
                        <button
                          type="button"
                          className="mod-danger-button"
                          disabled={busy === playerCase.id}
                          onClick={() =>
                            act(
                              playerCase.id,
                              async () => {
                                const expiresAt = suspensionExpiry(
                                  duration[playerCase.id] ?? "24h",
                                );
                                await createUserBan({
                                  userId: playerCase.reportedUserId as string,
                                  reason: note[playerCase.id],
                                  // So the suspended player can be shown what
                                  // the complaint was actually about.
                                  reportId: playerCase.id,
                                  ...(expiresAt ? { expiresAt } : {}),
                                });
                                // Acting on a report decides it. Leaving it
                                // pending puts it back in front of the next
                                // moderator, to look at something already done.
                                await reviewModerationReport(
                                  playerCase.id,
                                  "resolved",
                                  note[playerCase.id],
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
                          className="ops-select"
                          value={duration[playerCase.id] ?? "24h"}
                          onChange={(change) =>
                            setDuration((current) => ({
                              ...current,
                              [playerCase.id]: change.target.value,
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
                </>
              ) : (
                playerCase.resolutionNote && (
                  <p className="mod-resolution">{playerCase.resolutionNote}</p>
                )
              )}
            </>
          )}

          {contentCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>
                    Prompt content · #{contentCase.id.slice(0, 6)}
                  </SectionLabel>
                  <h1>{humanize(contentCase.reason)}</h1>
                  <p className="mod-case-meta">
                    Reported {formatWhen(contentCase.createdAt)}
                  </p>
                </div>
                <Chip kind="warm">{humanize(contentCase.reason)}</Chip>
              </div>

              <section className="ops-card" aria-label="Reported content">
                <h2>Reported content</h2>
                <blockquote className="mod-evidence">
                  <span>
                    {contentCase.targetType === "prompt" ? (
                      <>
                        Prompt <strong>{contentCase.prompt}</strong> in{" "}
                        {contentCase.listName}
                      </>
                    ) : (
                      <>
                        List <strong>{contentCase.listName}</strong>
                      </>
                    )}
                  </span>
                </blockquote>
                {contentCase.details && (
                  <p className="mod-evidence-caption">{contentCase.details}</p>
                )}
              </section>

              {contentCase.status === "pending" ? (
                <>
                  {noteField(contentCase.id)}
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "dismissed",
                              note[contentCase.id],
                            ),
                          "Dismissed.",
                        )
                      }
                    >
                      Dismiss
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "resolved",
                              note[contentCase.id],
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
                      className="mod-danger-button"
                      disabled={busy === contentCase.id}
                      onClick={() =>
                        act(
                          contentCase.id,
                          () =>
                            reviewPromptContentReport(
                              contentCase.id,
                              "resolved",
                              note[contentCase.id],
                              "hidden",
                            ),
                          "Hidden, and the owner is told if they have a confirmed address.",
                        )
                      }
                    >
                      Hide it
                    </button>
                  </div>
                </>
              ) : (
                contentCase.resolutionNote && (
                  <p className="mod-resolution">{contentCase.resolutionNote}</p>
                )
              )}
            </>
          )}

          {banCase && (
            <>
              <div className="mod-case-head">
                <div>
                  <SectionLabel>Suspension · #{banCase.id.slice(0, 6)}</SectionLabel>
                  <h1>{banCase.displayName ?? "Deleted player"}</h1>
                  <p className="mod-case-meta">
                    {banCase.isActive
                      ? banCase.expiresAt
                        ? `In force until ${formatWhen(banCase.expiresAt)}`
                        : "In force, with no end date"
                      : banCase.revokedAt
                        ? `Lifted ${formatWhen(banCase.revokedAt)}`
                        : "Expired"}
                  </p>
                </div>
                <Chip kind={banCase.isActive ? "danger" : "neutral"}>
                  {banCase.isActive ? "In force" : "Over"}
                </Chip>
              </div>

              <section className="ops-card" aria-label="Suspension reason">
                <h2>Why</h2>
                <p className="mod-case-details">{banCase.reason}</p>
                <p className="mod-evidence-caption">
                  Suspended {formatWhen(banCase.createdAt)}
                </p>
              </section>

              {banCase.isActive ? (
                <>
                  <label className="mod-note">
                    Reason for lifting
                    <textarea
                      placeholder="Why, in one line — required to decide"
                      value={note[banCase.id] ?? ""}
                      onChange={(change) =>
                        setNote((current) => ({
                          ...current,
                          [banCase.id]: change.target.value,
                        }))
                      }
                    />
                    <span className="mod-note-hint">
                      Kept in the append-only audit ledger.
                    </span>
                  </label>
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="mod-danger-button"
                      disabled={busy === banCase.id}
                      onClick={() =>
                        act(
                          banCase.id,
                          () => revokeUserBan(banCase.id, note[banCase.id]),
                          "Lifted. They can sign in again.",
                        )
                      }
                    >
                      Lift suspension
                    </button>
                  </div>
                </>
              ) : (
                banCase.revokeReason && (
                  <p className="mod-resolution">{banCase.revokeReason}</p>
                )
              )}
            </>
          )}

          {!playerCase && !contentCase && !banCase && (
            <p className="ops-empty">Nothing selected. The queue is clear.</p>
          )}
        </div>
      </div>
    </main>
  );
}
