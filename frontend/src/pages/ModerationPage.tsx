import { useClock } from "../hooks/useClock";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppHeader } from "../components/AppHeader";
import { NotFoundPage } from "./NotFoundPage";
import { ReportedDrawing } from "../components/ReportedDrawing";
import { Chip, type ChipKind } from "../components/ui/Chip";
import { SectionLabel } from "../components/ui/Card";

import { ApiError } from "../lib/api";
import {
  CLOSED_CASES_PAGE_SIZE,
  createUserBan,
  createUserWarning,
  fetchReportDrawing,
  listClosedCases,
  listModerationReports,
  listPromptContentReports,
  listUserBans,
  revokeUserBan,
  removeReportedAvatar,
  reviewModerationReport,
  reviewPromptContentReport,
  type PlayerReport,
  type PromptContentReport,
  type ReportOutcome,
  suspensionExpiry,
  SUSPENSION_DURATIONS,
  type UserBan,
} from "../lib/moderation";
import { canModerate } from "../lib/operatorAccess";
import { useAuthStore } from "../store/authStore";

type Filter = "open" | "players" | "content" | "bans" | "closed";
type CaseKind = "player" | "content" | "ban";
type Selection = { kind: CaseKind; id: string };

type QueueEntry = {
  kind: CaseKind;
  id: string;
  title: string;
  snippet: string;
  /** What the list is ordered by and dated with: when the case arrived, or
      for a closed one when it was decided. */
  at: string;
  dot: "danger" | "warning" | "neutral";
  /** How a closed case ended; absent while it is still open. */
  outcome?: ReportOutcome;
};

/** One chip per outcome: what was done, in the colour of how serious it was.
    Green for a case that ended with nothing against anyone, orange for a
    warning, red for a suspension or a takedown. */
const OUTCOMES: Record<ReportOutcome, { label: string; kind: ChipKind }> = {
  pending: { label: "Waiting", kind: "neutral" },
  dismissed: { label: "Dismissed", kind: "success" },
  resolved: { label: "Resolved", kind: "neutral" },
  warned: { label: "Warned", kind: "warning" },
  suspended: { label: "Suspended", kind: "danger" },
  hidden: { label: "Hidden", kind: "danger" },
  left_up: { label: "Left up", kind: "success" },
};

function OutcomeChip({ outcome }: { outcome: ReportOutcome }) {
  const { label, kind } = OUTCOMES[outcome] ?? OUTCOMES.resolved;
  return <Chip kind={kind} className="mod-outcome-chip">{label}</Chip>;
}

/** How a closed case was decided: the outcome, who decided it and when, and
    the note they left. The note alone used to stand for all three. */
function DecisionCard({
  report,
  dateTime,
}: {
  report: PlayerReport | PromptContentReport;
  dateTime: (date: Date) => string;
}) {
  return (
    <section className="ops-card mod-decision" aria-label="Decision" data-testid="mod-decision">
      <div className="mod-decision-head">
        <h2>Decision</h2>
        <OutcomeChip outcome={report.outcome} />
      </div>
      <p className="mod-case-meta">
        {report.reviewedBy ? `By ${report.reviewedBy}` : "Reviewer no longer has an account"}
        {report.reviewedAt ? ` · ${formatWhen(report.reviewedAt, dateTime)}` : ""}
      </p>
      {report.resolutionNote && (
        <p className="mod-resolution">{report.resolutionNote}</p>
      )}
    </section>
  );
}

const FILTERS: { name: Filter; label: string }[] = [
  { name: "open", label: "All open" },
  { name: "players", label: "Player reports" },
  { name: "content", label: "Prompt content" },
  { name: "bans", label: "Suspensions" },
  { name: "closed", label: "Closed" },
];

/** When a decided case was decided. The review stamps it; the last write
    stands in for a row decided some other way. */
function decidedAt(report: PlayerReport | PromptContentReport): string {
  return report.reviewedAt ?? report.updatedAt;
}

function formatWhen(value: string, dateTime: (date: Date) => string): string {
  return dateTime(new Date(value));
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

/** Account age in the coarsest sensible unit, for the context card. */
function accountAge(createdAt: string): string {
  const days = Math.max(0, Math.floor((Date.now() - Date.parse(createdAt)) / 86400000));
  if (days < 1) return "Today";
  if (days < 31) return `${days} day${days === 1 ? "" : "s"}`;
  if (days < 365) {
    const months = Math.floor(days / 30);
    return `${months} month${months === 1 ? "" : "s"}`;
  }
  const years = Math.floor(days / 365);
  return `${years} year${years === 1 ? "" : "s"}`;
}

/** The drawing a report carries, for the case view. */
function ReportDrawing({
  reportId,
  drawing,
  drawerName,
  dateTime,
}: {
  reportId: string;
  drawing: NonNullable<PlayerReport["drawing"]>;
  drawerName: string;
  dateTime: (date: Date) => string;
}) {
  return (
    <ReportedDrawing
      className="mod-drawing"
      testId="mod-drawing"
      load={() => fetchReportDrawing(reportId)}
      label={`${drawerName}'s drawing of ${drawing.prompt}, as it was when reported`}
      caption={
        <>
          The canvas when the report was sent, {formatWhen(drawing.capturedAt, dateTime)}:
          round {drawing.roundNumber}, {drawing.actionCount} action
          {drawing.actionCount === 1 ? "" : "s"}. They were asked to draw{" "}
          <strong>{drawing.prompt || "nothing yet"}</strong>.
        </>
      }
    />
  );
}

export function ModerationPage() {
  const { dateTime } = useClock();
  const user = useAuthStore((state) => state.user);
  const hasResolved = useAuthStore((state) => state.hasResolved);
  const [filter, setFilter] = useState<Filter>("open");
  // Which page of closed cases is open, and whether an older one exists.
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
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
  const showingClosed = filter === "closed";

  const fail = useCallback((problem: unknown) => {
    setError(
      problem instanceof ApiError
        ? problem.message
        : "Could not reach the moderation queue.",
    );
  }, []);

  const load = useCallback(() => {
    if (!allowed) return;
    // The open queues are the pending work, whatever is being viewed: the
    // "N open" chip counts them even while a closed page is on screen.
    const pending = Promise.all([
      listModerationReports("pending"),
      listPromptContentReports("pending"),
    ]);
    // Closed cases are paged by the server, newest decision first, because
    // they accumulate for as long as the service runs; the open queues are
    // small enough to hold whole.
    const cases = showingClosed
      ? listClosedCases({
          limit: CLOSED_CASES_PAGE_SIZE,
          offset: page * CLOSED_CASES_PAGE_SIZE,
        })
      : pending.then(([playerResult, contentResult]) => ({
          players: playerResult.reports,
          content: contentResult.reports,
          hasMore: false,
        }));
    void Promise.all([
      cases,
      // Everything, not only what is in force: a suspension that has been
      // lifted or has expired is part of the record of what was done.
      listUserBans(),
      pending,
    ])
      .then(([caseResult, banResult, pendingResult]) => {
        setPlayers(caseResult.players);
        setContent(caseResult.content);
        setHasMore(caseResult.hasMore);
        setBans(banResult.bans);
        setOpenCount(
          pendingResult[0].reports.length + pendingResult[1].reports.length,
        );
        setError(null);
      })
      .catch(fail);
  }, [allowed, showingClosed, page, fail]);

  useEffect(load, [load]);

  // A page is a position in the closed stream and means nothing elsewhere.
  function changeFilter(next: Filter) {
    setFilter(next);
    setPage(0);
  }

  const queue = useMemo<QueueEntry[]>(() => {
    // A closed case is dated by its decision and marked as settled; an open
    // one by its arrival and by what kind of trouble it is.
    const playerEntries: QueueEntry[] = players.map((report) => ({
      kind: "player",
      id: report.id,
      title: humanize(report.reason),
      // A room report may say nothing beyond its evidence.
      snippet: report.details || "No details given.",
      at: showingClosed ? decidedAt(report) : report.createdAt,
      dot: showingClosed ? "neutral" : "danger",
      outcome: showingClosed ? report.outcome : undefined,
    }));
    const contentEntries: QueueEntry[] = content.map((report) => ({
      kind: "content",
      id: report.id,
      title: humanize(report.reason),
      snippet:
        report.targetType === "prompt"
          ? `Prompt “${report.prompt}” in ${report.listName ?? "a list"}`
          : `List “${report.listName}”`,
      at: showingClosed ? decidedAt(report) : report.createdAt,
      dot: showingClosed ? "neutral" : "warning",
      outcome: showingClosed ? report.outcome : undefined,
    }));
    const banEntries: QueueEntry[] = bans.map((ban) => ({
      kind: "ban",
      id: ban.id,
      title: ban.displayName ?? "Deleted player",
      snippet: ban.reason,
      at: ban.createdAt,
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
    return entries.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  }, [filter, showingClosed, players, content, bans]);

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
    // The same answer the API gives this account. A page that names the
    // surface and refuses it confirms the surface exists; R-ROLE-01 has every
    // endpoint behind these entries answer 404 rather than 403, and the door
    // in front of them should say the same thing.
    return <NotFoundPage />;
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
        Kept in the append-only audit ledger. A warning or suspension from
        here also resolves this report.
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
                onClick={() => changeFilter(name)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="mod-queue-list">
            {queue.length === 0 && (
              <p className="ops-empty">
                {filter === "bans"
                  ? "Nobody has been suspended."
                  : showingClosed
                    ? page > 0
                      ? "No older cases."
                      : "No case has been decided yet."
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
                    {entry.outcome && <OutcomeChip outcome={entry.outcome} />}
                    <span>{entry.snippet}</span>
                  </span>
                  <time dateTime={entry.at}>{age(entry.at)}</time>
                </button>
              );
            })}
          </div>
          {showingClosed && (
            <nav className="mod-pager" aria-label="Closed cases pages">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
              >
                Newer
              </button>
              <span className="mod-pager-page">Page {page + 1}</span>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!hasMore}
                onClick={() => setPage((current) => current + 1)}
              >
                Older
              </button>
            </nav>
          )}
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
                    {playerCase.reportedPlayer
                      ? `About ${playerCase.reportedPlayer.displayName} · reported ${formatWhen(playerCase.createdAt, dateTime)}`
                      : `Reported ${formatWhen(playerCase.createdAt, dateTime)}`}
                  </p>
                </div>
                <Chip kind="danger">{humanize(playerCase.reason)}</Chip>
              </div>

              <div className="mod-case-columns">
                <section className="ops-card" aria-label="Reported evidence">
                  <h2>Reported evidence</h2>
                  <p className="mod-case-details">
                    {playerCase.details || "The reporter gave no details; the evidence is the complaint."}
                  </p>
                  {playerCase.messageEvidence.length > 0 && (
                    <>
                      {/* One thread, in the order it was said: the cited
                          lines marked, and around them what everyone else
                          said, dimmed. A line on its own is often
                          unreadable; the conversation is what a moderator
                          judges. */}
                      <blockquote className="mod-evidence">
                        {playerCase.messageEvidence.map((line) => (
                          <span
                            key={line.sourceMessageId}
                            className={`mod-evidence-line is-${line.role}`}
                            data-role={line.role}
                          >
                            <strong>{line.senderDisplayName}:</strong> {line.text}
                            {/* The snapshot is the evidence. The live message
                                may have been deleted since, which is the point
                                of keeping one. */}
                            {!line.sourceAvailable && (
                              <em> — original no longer in the room</em>
                            )}
                          </span>
                        ))}
                      </blockquote>
                      <p className="mod-evidence-caption">
                        Marked lines are the ones reported — up to 20, pinned
                        by the server exactly as the reporter received them.
                        The rest is what was said around them: up to 10 lines
                        before and 5 after, within 12 hours, as the reporter
                        saw it.
                      </p>
                    </>
                  )}
                  {playerCase.drawing ? (
                    <ReportDrawing
                      key={playerCase.id}
                      reportId={playerCase.id}
                      drawing={playerCase.drawing}
                      drawerName={
                        playerCase.reportedPlayer?.displayName ?? "The reported player"
                      }
                      dateTime={dateTime}
                    />
                  ) : (
                    playerCase.reason === "offensive_drawing" && (
                      <p className="mod-evidence-caption">
                        No drawing was attached: the reporter did not include
                        it, or the reported player was not drawing at the time.
                      </p>
                    )
                  )}
                </section>
                <aside className="ops-card" aria-label="Account context">
                  <h2>Account context</h2>
                  {playerCase.reportedPlayer ? (
                    <>
                      <div className="mod-context-row">
                        <span>Player</span>
                        <strong>{playerCase.reportedPlayer.displayName}</strong>
                      </div>
                      {playerCase.reportedPlayer.avatarUrl && (
                        <div className="mod-context-row">
                          <span>Picture</span>
                          {/* Shown at the size a player list shows it, and
                              at full size on hover: the case may be about it. */}
                          <img
                            className="mod-context-avatar"
                            src={playerCase.reportedPlayer.avatarUrl}
                            alt={`${playerCase.reportedPlayer.displayName}'s picture`}
                          />
                        </div>
                      )}
                      <div className="mod-context-row">
                        <span>Account</span>
                        <strong>
                          {playerCase.reportedPlayer.registered
                            ? "Registered"
                            : "Guest"}
                        </strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Age</span>
                        <strong>{accountAge(playerCase.reportedPlayer.createdAt)}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Prior reports</span>
                        <strong>{playerCase.reportedPlayer.priorReports}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Warnings</span>
                        <strong>{playerCase.reportedPlayer.priorWarnings}</strong>
                      </div>
                      <div className="mod-context-row">
                        <span>Active suspension</span>
                        <strong>
                          {playerCase.reportedPlayer.activeSuspension
                            ? "In force"
                            : "None"}
                        </strong>
                      </div>
                    </>
                  ) : (
                    <p className="mod-case-details">
                      The account behind this report no longer exists.
                    </p>
                  )}
                </aside>
              </div>

              {playerCase.status === "pending" ? (
                <>
                  {noteField(playerCase.id)}
                  <div className="mod-actions">
                    <button
                      type="button"
                      className="btn btn-success"
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
                    {/* Warning and suspending both need an account to act on;
                        a report about an accountless seat can only be closed,
                        so a plain Resolve stands in for those. */}
                    {!playerCase.reportedUserId && (
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
                    )}
                    {playerCase.reportedUserId && playerCase.reportedPlayer?.avatarUrl && (
                      <button
                        type="button"
                        className="btn btn-danger-ghost"
                        disabled={busy === playerCase.id}
                        onClick={() =>
                          act(
                            playerCase.id,
                            () => removeReportedAvatar(playerCase.id),
                            "Picture removed. They cannot upload another for a week.",
                          )
                        }
                      >
                        Remove picture
                      </button>
                    )}
                    {playerCase.reportedUserId && (
                      <>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={busy === playerCase.id}
                          onClick={() =>
                            act(
                              playerCase.id,
                              () =>
                                // One request: the server resolves the report
                                // in the same transaction as the warning.
                                createUserWarning({
                                  userId: playerCase.reportedUserId as string,
                                  reason: note[playerCase.id],
                                  // So the warned player can be shown what
                                  // the complaint was actually about.
                                  reportId: playerCase.id,
                                }),
                              "Warned, and the report resolved. They will see it the next time they open Sketchy.",
                            )
                          }
                        >
                          Warn player
                        </button>
                        <button
                          type="button"
                          className="mod-danger-button"
                          disabled={busy === playerCase.id}
                          onClick={() =>
                            act(
                              playerCase.id,
                              () => {
                                const expiresAt = suspensionExpiry(
                                  duration[playerCase.id] ?? "24h",
                                );
                                // One request: the server resolves the report
                                // in the same transaction as the suspension.
                                return createUserBan({
                                  userId: playerCase.reportedUserId as string,
                                  reason: note[playerCase.id],
                                  // So the suspended player can be shown what
                                  // the complaint was actually about.
                                  reportId: playerCase.id,
                                  ...(expiresAt ? { expiresAt } : {}),
                                });
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
                <DecisionCard report={playerCase} dateTime={dateTime} />
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
                    Reported {formatWhen(contentCase.createdAt, dateTime)}
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
                      className="btn btn-success"
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
                <DecisionCard report={contentCase} dateTime={dateTime} />
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
                        ? `In force until ${formatWhen(banCase.expiresAt, dateTime)}`
                        : "In force, with no end date"
                      : banCase.revokedAt
                        ? `Lifted ${formatWhen(banCase.revokedAt, dateTime)}`
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
                  Suspended {formatWhen(banCase.createdAt, dateTime)}
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
